#!/usr/bin/env python3
"""Compare generated tables with eso_locations and write a Markdown log."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path


INSTRUMENT_DIRECTORY = re.compile(r"-([A-Z])-(\d+)$")
UNCOVERED_HEADER = "\t".join(
    (
        "legacy_timestamp",
        "log_before",
        "log_after",
        "mer_before",
        "mer_after",
    )
)


def read_rows(path: Path) -> list[tuple]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) != 15:
            continue
        time = datetime.strptime(f"{fields[1]} {fields[2]}", "%d-%b-%Y %H:%M:%S").replace(tzinfo=timezone.utc)
        rows.append((time, float(fields[3]), float(fields[4]), tuple(fields[7:12])))
    return sorted(rows)


def distance_m(a: tuple, b: tuple) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[1], a[2], b[1], b[2]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(h))


def nearest(row: tuple, reference: list[tuple]) -> tuple | None:
    if not reference:
        return None
    times = [x[0] for x in reference]
    index = bisect.bisect_left(times, row[0])
    choices = reference[max(0, index - 1) : index + 1]
    return min(choices, key=lambda x: abs((x[0] - row[0]).total_seconds()))


def median(values: list[float]) -> str:
    return f"{statistics.median(values):.1f}" if values else "n/a"


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def read_source_times(
    path: Path | None,
    time_field: str,
    kind: tuple[str, str] | None = None,
) -> list[tuple[datetime, str]]:
    result = []
    if path is None:
        return result
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
            if kind and row.get(kind[0]) != kind[1]:
                continue
            time = parse_time(row.get(time_field))
            source_file = row.get("source_file")
            if time and source_file:
                result.append((time, str(source_file)))
    return sorted(result)


def family_file(directory: Path | None, family: str) -> Path | None:
    if directory is None:
        return None
    matches = sorted(directory.glob(f"{family}.*.jsonl"))
    return matches[0] if matches else None


def station_directories(root: Path) -> dict[str, Path]:
    result = {}
    if not root.is_dir():
        return result
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        match = INSTRUMENT_DIRECTORY.search(directory.name)
        if match:
            result[f"{match.group(1)}{int(match.group(2)):04d}"] = directory
    return result


def surrounding_files(events: list[tuple[datetime, str]], target: datetime) -> tuple[str, str]:
    times = [event[0] for event in events]
    before_index = bisect.bisect_left(times, target) - 1
    after_index = bisect.bisect_right(times, target)
    before = events[before_index][1] if before_index >= 0 else "<none>"
    after = events[after_index][1] if after_index < len(events) else "<none>"
    return before, after


def write_uncovered_times(
    path: Path,
    uncovered_times: list[datetime],
    log_events: list[tuple[datetime, str]],
    mer_events: list[tuple[datetime, str]],
) -> None:
    lines = [UNCOVERED_HEADER]
    for legacy_time in uncovered_times:
        log_before, log_after = surrounding_files(log_events, legacy_time)
        mer_before, mer_after = surrounding_files(mer_events, legacy_time)
        lines.append(
            "\t".join(
                (
                    legacy_time.isoformat().replace("+00:00", "Z"),
                    log_before,
                    log_after,
                    mer_before,
                    mer_after,
                )
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path, help="directory containing generated *_all.txt tables")
    parser.add_argument(
        "--legacy",
        type=Path,
        default=Path("~/mermaid/esoloc"),
        help="directory containing legacy *_all.txt tables (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the Markdown comparison log to this file (default: stdout only)",
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=Path("~/mermaid/records"),
        help="normalized records root used to find bracketing source files (default: %(default)s)",
    )
    parser.add_argument(
        "--uncovered-output",
        type=Path,
        help="directory for per-float uncovered-time files (default: beside OUTPUT, or GENERATED)",
    )
    parser.add_argument(
        "--coverage-seconds",
        type=int,
        default=300,
        help="maximum offset for a legacy row to count as covered (default: %(default)s)",
    )
    parser.add_argument("--instruments", nargs="*", help="limit comparison to station IDs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uncovered_output = args.uncovered_output
    if uncovered_output is None:
        uncovered_output = args.output.parent if args.output else args.generated
    uncovered_output = uncovered_output.expanduser()
    uncovered_output.mkdir(parents=True, exist_ok=True)
    records_root = args.records.expanduser()
    if not records_root.is_dir():
        raise SystemExit(f"normalized records root is not a directory: {records_root}")
    record_directories = station_directories(records_root)
    lines = [
        "# eso_locations comparison",
        "",
        f"Generated: `{args.generated.resolve()}`",
        f"Untrusted derived comparison set: `{args.legacy.expanduser().resolve()}`",
        f"Normalized records: `{records_root.resolve()}`",
        f"Uncovered-time files: `{uncovered_output.resolve()}`",
        "",
        "The normalized-record product is authoritative; this is a difference log, not a pass/fail test.",
        "",
        f"A legacy row with no normalized GPS row within {args.coverage_seconds} seconds is flagged as uncovered.",
        "",
        "| Instrument | Generated | Legacy | Delta | Legacy uncovered | Median abs(dt) (s) | Median distance (m) | Exact vital tuple |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    legacy_root = args.legacy.expanduser()
    names = {x.name for x in args.generated.glob("*_all.txt")} | {x.name for x in legacy_root.glob("*_all.txt")}
    if args.instruments:
        wanted = {f"{station}_all.txt" for station in args.instruments}
        names &= wanted
    for name in sorted(names):
        station = name.removesuffix("_all.txt")
        generated = read_rows(args.generated / name)
        legacy = read_rows(legacy_root / name)
        offsets, distances, exact = [], [], 0
        uncovered = 0
        uncovered_times = []
        for row in legacy:
            match = nearest(row, generated)
            if match:
                offsets.append(abs((match[0] - row[0]).total_seconds()))
                distances.append(distance_m(row, match))
                exact += row[3] == match[3]
            if match is None or abs((match[0] - row[0]).total_seconds()) > args.coverage_seconds:
                uncovered += 1
                uncovered_times.append(row[0])
        record_directory = record_directories.get(station)
        log_events = read_source_times(
            family_file(record_directory, "log_gps_records"),
            "record_time",
        )
        mer_events = read_source_times(
            family_file(record_directory, "mer_environment_records"),
            "gpsinfo_date",
            ("environment_kind", "gpsinfo"),
        )
        write_uncovered_times(
            uncovered_output / f"{station}_uncovered_time.txt",
            uncovered_times,
            log_events,
            mer_events,
        )
        lines.append(
            f"| {station} | {len(generated)} | {len(legacy)} | {len(generated) - len(legacy):+d} | {uncovered} | "
            f"{median(offsets)} | {median(distances)} | {exact}/{len(legacy)} |"
        )
        if uncovered_times:
            shown = ", ".join(x.isoformat().replace("+00:00", "Z") for x in uncovered_times[:10])
            suffix = " ..." if len(uncovered_times) > 10 else ""
            lines.append(f"\n`{station}` uncovered legacy times: {shown}{suffix}\n")
    text = "\n".join(lines) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
