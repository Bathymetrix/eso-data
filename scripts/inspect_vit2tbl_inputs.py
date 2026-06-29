#!/usr/bin/env python3
"""Inspect normalized MERMAID records relevant to a VIT2TBL-like product.

The script is deliberately read-only and uses only Python's standard library.
It reports family counts, sampled schemas, and timestamp/provenance diagnostics
for candidate joins around each GPS position fix.
"""

from __future__ import annotations

import argparse
import bisect
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator


DEFAULT_INSTRUMENTS = (
    "452.020-P-23",
    "452.020-P-0050",
    "452.020-P-06",
    "452.112-N-01",
    "452.120-R-0058",
    "465.152-R-0001",
    "467.164-T-0102",
    "467.174-W-0114",
)

FAMILIES = (
    "log_gps_records",
    "log_battery_records",
    "log_pressure_temperature_records",
    "log_iridium_records",
    "mer_environment_records",
)


@dataclass(frozen=True)
class Event:
    epoch: int
    source_file: str
    value: object


def family_path(instrument_dir: Path, family: str) -> Path | None:
    matches = sorted(instrument_dir.glob(f"{family}.*.jsonl"))
    return matches[0] if matches else None


def iter_jsonl(path: Path | None) -> Iterator[dict]:
    if path is None or not path.exists():
        return
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc


def count_lines_and_sample_fields(path: Path | None, sample_limit: int) -> tuple[int, set[str]]:
    if path is None or not path.exists():
        return 0, set()
    count = 0
    fields: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            count += 1
            if count <= sample_limit:
                fields.update(json.loads(line).keys())
    return count, fields


def epoch(record: dict) -> int | None:
    value = record.get("log_epoch_time")
    if value is None:
        time_text = record.get("record_time") or record.get("gpsinfo_date")
        if not time_text:
            return None
        try:
            return int(datetime.fromisoformat(time_text.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp())
        except ValueError:
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event(record: dict, value: object) -> Event | None:
    timestamp = epoch(record)
    source_file = record.get("source_file")
    if timestamp is None or not source_file:
        return None
    return Event(timestamp, str(source_file), value)


def parse_gps(path: Path | None) -> tuple[list[Event], list[Event], Counter]:
    fixes: list[Event] = []
    dops: list[Event] = []
    kinds: Counter = Counter()
    for record in iter_jsonl(path):
        kind = record.get("gps_record_kind")
        kinds[kind or "<missing>"] += 1
        raw_values = record.get("raw_values") or {}
        if kind == "fix_position":
            item = event(record, (raw_values.get("latitude"), raw_values.get("longitude")))
            if item:
                fixes.append(item)
        elif kind == "dop":
            item = event(record, (raw_values.get("hdop"), raw_values.get("vdop")))
            if item:
                dops.append(item)
    return sorted(fixes, key=lambda item: item.epoch), sorted(dops, key=lambda item: item.epoch), kinds


def parse_mer_gps(path: Path | None) -> list[Event]:
    fixes: list[Event] = []
    for record in iter_jsonl(path):
        if record.get("environment_kind") != "gpsinfo":
            continue
        raw_values = record.get("raw_values") or {}
        item = event(record, (raw_values.get("lat"), raw_values.get("lon")))
        if item:
            fixes.append(item)
    return sorted(fixes, key=lambda item: item.epoch)


def parse_battery(path: Path | None) -> list[Event]:
    result: list[Event] = []
    for record in iter_jsonl(path):
        if record.get("voltage_mv") is None:
            continue
        item = event(record, (record.get("voltage_mv"), record.get("minimum_voltage_mv")))
        if item:
            result.append(item)
    return sorted(result, key=lambda item: item.epoch)


def parse_pressure(path: Path | None) -> dict[str, list[Event]]:
    result: dict[str, list[Event]] = {"internal": [], "external": []}
    for record in iter_jsonl(path):
        if record.get("internal_pressure_pa") is not None:
            item = event(record, record.get("internal_pressure_pa"))
            if item:
                result["internal"].append(item)
        if record.get("external_pressure_mbar") is not None:
            item = event(record, (record.get("external_pressure_mbar"), record.get("external_pressure_range_mbar")))
            if item:
                result["external"].append(item)
    for values in result.values():
        values.sort(key=lambda item: item.epoch)
    return result


def first_present(mapping: dict, *keys: str) -> object | None:
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def parse_iridium(path: Path | None) -> dict[str, list[Event]]:
    result: dict[str, list[Event]] = {"commands": [], "uploads": []}
    for record in iter_jsonl(path):
        for nested in record.get("iridium_events") or (record,):
            kind = nested.get("iridium_event_kind") or nested.get("transmission_kind")
            source = dict(record)
            source.update(nested)
            command_count = first_present(source, "received_command_count", "n_commands_received", "command_count")
            upload_count = first_present(source, "uploaded_file_count", "n_files_uploaded")
            if kind == "command_summary" and command_count is not None:
                item = event(source, int(command_count))
                if item:
                    result["commands"].append(item)
            elif kind == "upload_session_summary" and upload_count is not None:
                item = event(source, int(upload_count))
                if item:
                    result["uploads"].append(item)
    for values in result.values():
        values.sort(key=lambda item: item.epoch)
    return result


def previous_event(events: list[Event], anchor: Event) -> Event | None:
    epochs = [item.epoch for item in events]
    index = bisect.bisect_right(epochs, anchor.epoch) - 1
    return events[index] if index >= 0 else None


def next_session_event(events: list[Event], fixes: list[Event], fix_index: int, max_seconds: int) -> Event | None:
    anchor = fixes[fix_index]
    next_fix_epoch = fixes[fix_index + 1].epoch if fix_index + 1 < len(fixes) else anchor.epoch + max_seconds + 1
    stop_epoch = min(next_fix_epoch, anchor.epoch + max_seconds + 1)
    epochs = [item.epoch for item in events]
    index = bisect.bisect_left(epochs, anchor.epoch)
    while index < len(events) and events[index].epoch < stop_epoch:
        candidate = events[index]
        if candidate.source_file == anchor.source_file:
            return candidate
        index += 1
    return None


def percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * fraction)
    return ordered[index]


def fmt_offset_summary(offsets: list[int]) -> str:
    if not offsets:
        return "no matches"
    return (
        f"n={len(offsets)} median={statistics.median(offsets):g}s "
        f"p90={percentile(offsets, 0.90)}s min={min(offsets)}s max={max(offsets)}s"
    )


def previous_diagnostics(fixes: list[Event], candidates: list[Event], freshness_seconds: int) -> str:
    offsets: list[int] = []
    same_source = 0
    for anchor in fixes:
        match = previous_event(candidates, anchor)
        if not match:
            continue
        offsets.append(anchor.epoch - match.epoch)
        same_source += match.source_file == anchor.source_file
    fresh = sum(offset <= freshness_seconds for offset in offsets)
    return (
        f"{fmt_offset_summary(offsets)} fresh<={freshness_seconds}s={fresh}/{len(fixes)} "
        f"same_source={same_source}/{len(offsets)}"
    )


def nearest_diagnostics(fixes: list[Event], candidates: list[Event], max_seconds: int) -> str:
    offsets: list[int] = []
    same_source = 0
    candidate_epochs = [item.epoch for item in candidates]
    pairs = []
    for anchor_index, anchor in enumerate(fixes):
        start = bisect.bisect_left(candidate_epochs, anchor.epoch - max_seconds)
        stop = bisect.bisect_right(candidate_epochs, anchor.epoch + max_seconds)
        for candidate_index in range(start, stop):
            candidate = candidates[candidate_index]
            source_penalty = 0 if candidate.source_file == anchor.source_file else 1
            pairs.append((source_penalty, abs(candidate.epoch - anchor.epoch), anchor_index, candidate_index))
    used_anchors: set[int] = set()
    used_candidates: set[int] = set()
    for _, _, anchor_index, candidate_index in sorted(pairs):
        if anchor_index in used_anchors or candidate_index in used_candidates:
            continue
        anchor = fixes[anchor_index]
        match = candidates[candidate_index]
        offsets.append(match.epoch - anchor.epoch)
        same_source += match.source_file == anchor.source_file
        used_anchors.add(anchor_index)
        used_candidates.add(candidate_index)
    return f"{fmt_offset_summary(offsets)} missing={len(fixes) - len(offsets)}/{len(fixes)} same_source={same_source}/{len(offsets)}"


def session_diagnostics(fixes: list[Event], candidates: list[Event], max_seconds: int) -> str:
    offsets: list[int] = []
    for index, anchor in enumerate(fixes):
        match = next_session_event(candidates, fixes, index, max_seconds)
        if match:
            offsets.append(match.epoch - anchor.epoch)
    return f"{fmt_offset_summary(offsets)} missing={len(fixes) - len(offsets)}/{len(fixes)}"


def exact_dop_diagnostics(fixes: list[Event], dops: list[Event]) -> str:
    dop_keys = {(item.source_file, item.epoch) for item in dops}
    exact = sum((item.source_file, item.epoch) in dop_keys for item in fixes)
    return f"exact_same_source_time={exact}/{len(fixes)} missing={len(fixes) - exact}/{len(fixes)}"


def inspect_instrument(
    instrument_dir: Path,
    sample_limit: int,
    dop_seconds: int,
    session_seconds: int,
    freshness_seconds: int,
    show_fields: bool,
) -> None:
    print(f"\n## {instrument_dir.name}")
    paths = {family: family_path(instrument_dir, family) for family in FAMILIES}
    counts: dict[str, int] = {}
    fields: dict[str, set[str]] = {}
    for family in FAMILIES:
        counts[family], fields[family] = count_lines_and_sample_fields(paths[family], sample_limit)

    print("counts:")
    for family in FAMILIES:
        print(f"  {family:34s} {counts[family]:9d}")

    fixes, dops, gps_kinds = parse_gps(paths["log_gps_records"])
    mer_fixes = parse_mer_gps(paths["mer_environment_records"])
    all_fixes = sorted(fixes + mer_fixes, key=lambda item: item.epoch)
    batteries = parse_battery(paths["log_battery_records"])
    pressures = parse_pressure(paths["log_pressure_temperature_records"])
    iridium = parse_iridium(paths["log_iridium_records"])

    print(f"gps kinds: {dict(sorted(gps_kinds.items(), key=lambda item: str(item[0])))}")
    print(f"position anchors: log={len(fixes)} mer={len(mer_fixes)} total={len(all_fixes)}")
    print(f"dop:       {nearest_diagnostics(fixes, dops, dop_seconds)}")
    print(f"battery:   {nearest_diagnostics(all_fixes, batteries, freshness_seconds)}")
    print(f"pint:      {nearest_diagnostics(all_fixes, pressures['internal'], freshness_seconds)}")
    print(f"pext:      {nearest_diagnostics(all_fixes, pressures['external'], freshness_seconds)}")
    print(f"commands:  {nearest_diagnostics(all_fixes, iridium['commands'], session_seconds)}")
    print(f"uploads:   {nearest_diagnostics(all_fixes, iridium['uploads'], session_seconds)}")
    print("queued count messages parsed: 0")

    if show_fields:
        print("sampled top-level fields:")
        for family in FAMILIES:
            joined = ", ".join(sorted(fields[family])) or "<none>"
            print(f"  {family}: {joined}")


def instrument_directories(root: Path, requested: Iterable[str], all_instruments: bool) -> list[Path]:
    if all_instruments:
        return sorted(path for path in root.iterdir() if path.is_dir() and not path.name.startswith("."))
    result = []
    for name in requested:
        path = root / name
        if not path.is_dir():
            raise FileNotFoundError(f"instrument directory not found: {path}")
        result.append(path)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("~/mermaid/records").expanduser(),
        help="normalized records root (default: ~/mermaid/records)",
    )
    parser.add_argument(
        "--instruments",
        nargs="+",
        default=list(DEFAULT_INSTRUMENTS),
        help="instrument directory names to inspect",
    )
    parser.add_argument("--all", action="store_true", help="inspect every instrument directory")
    parser.add_argument(
        "--dop-seconds",
        type=int,
        default=300,
        help="maximum DOP join offset reported in diagnostics (default: 300)",
    )
    parser.add_argument(
        "--session-seconds",
        type=int,
        default=1800,
        help="maximum forward window for command/upload session matching (default: 1800)",
    )
    parser.add_argument(
        "--freshness-seconds",
        type=int,
        default=21600,
        help="freshness threshold reported for previous-value joins (default: 21600 / 6 hours)",
    )
    parser.add_argument(
        "--schema-sample-limit",
        type=int,
        default=100,
        help="records per family used to collect top-level field names (default: 100)",
    )
    parser.add_argument("--show-fields", action="store_true", help="print sampled top-level fields")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"records root is not a directory: {root}")
    directories = instrument_directories(root, args.instruments, args.all)
    print(f"records root: {root}")
    print(f"instrument count: {len(directories)}")
    for directory in directories:
        inspect_instrument(
            directory,
            sample_limit=args.schema_sample_limit,
            dop_seconds=args.dop_seconds,
            session_seconds=args.session_seconds,
            freshness_seconds=args.freshness_seconds,
            show_fields=args.show_fields,
        )


if __name__ == "__main__":
    main()
