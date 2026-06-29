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
import re
import statistics
from collections import Counter
from dataclasses import dataclass
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
    "log_transmission_records",
    "log_operational_records",
    "log_unclassified_records",
    "mer_environment_records",
)

VBAT_RE = re.compile(r"\bVbat\s+(-?\d+)mV\s+\(min\s+(-?\d+)mV\)", re.I)
PINT_RE = re.compile(r"\b(?:Pint|internal pressure)\s+(-?\d+)Pa\b", re.I)
PEXT_RE = re.compile(r"\bPext\s*([+-]?\d+)mbar\s+\(rng\s+(-?\d+)mbar\)", re.I)
COMMAND_RE = re.compile(r"\b(\d+)\s+cmd\(s\) received\b", re.I)
QUEUED_RE = re.compile(r"\b(\d+)\s+file\(s\) queued\b", re.I)


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


def parse_operational(path: Path | None) -> dict[str, list[Event]]:
    result: dict[str, list[Event]] = {
        "vbat": [],
        "pint": [],
        "pext": [],
        "commands": [],
        "queued": [],
    }
    for record in iter_jsonl(path):
        message = str(record.get("message") or "")
        for name, regex in (
            ("vbat", VBAT_RE),
            ("pint", PINT_RE),
            ("pext", PEXT_RE),
            ("commands", COMMAND_RE),
            ("queued", QUEUED_RE),
        ):
            match = regex.search(message)
            if not match:
                continue
            values = tuple(int(value) for value in match.groups())
            item = event(record, values[0] if len(values) == 1 else values)
            if item:
                result[name].append(item)
    for values in result.values():
        values.sort(key=lambda item: item.epoch)
    return result


def parse_upload_summaries(path: Path | None) -> list[Event]:
    summaries: list[Event] = []
    for record in iter_jsonl(path):
        value = record.get("uploaded_file_count")
        if value is None:
            continue
        item = event(record, int(value))
        if item:
            summaries.append(item)
    return sorted(summaries, key=lambda item: item.epoch)


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
    operational = parse_operational(paths["log_operational_records"])
    uploads = parse_upload_summaries(paths["log_transmission_records"])

    print(f"gps kinds: {dict(sorted(gps_kinds.items(), key=lambda item: str(item[0])))}")
    print(f"position anchors: {len(fixes)}")
    print(f"dop:       {exact_dop_diagnostics(fixes, dops)}")
    print(f"vbat<=gps: {previous_diagnostics(fixes, operational['vbat'], freshness_seconds)}")
    print(f"pint<=gps: {previous_diagnostics(fixes, operational['pint'], freshness_seconds)}")
    print(f"pext<=gps: {previous_diagnostics(fixes, operational['pext'], freshness_seconds)}")
    print(
        f"cmd>gps:   {session_diagnostics(fixes, operational['commands'], session_seconds)} "
        f"(same source, before next fix, <= {session_seconds}s)"
    )
    print(
        f"up>gps:    {session_diagnostics(fixes, uploads, session_seconds)} "
        f"(same source, before next fix, <= {session_seconds}s)"
    )
    print(f"queued count messages parsed: {len(operational['queued'])}")

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
            session_seconds=args.session_seconds,
            freshness_seconds=args.freshness_seconds,
            show_fields=args.show_fields,
        )


if __name__ == "__main__":
    main()
