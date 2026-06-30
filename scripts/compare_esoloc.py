#!/usr/bin/env python3
"""Compare generated tables with eso_locations and write a plain-text log."""

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
UNMATCHED_HEADER = "\t".join(
    (
        "legacy_timestamp",
        "log_before",
        "log_after",
        "mer_before",
        "mer_after",
    )
)
SUMMARY_COLUMNS = (
    "Instrument",
    "Generated",
    "Legacy",
    "Delta",
    "Legacy matched",
    "Legacy unmatched",
    "Matched median abs(dt) (s)",
    "Matched median distance (m)",
    "Max matched distance legacy timestamp",
)
LEFT_ALIGNED_COLUMNS = {0, 8}


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
    if not values or any(not math.isfinite(value) for value in values):
        return "nan"
    return f"{statistics.median(values):.1f}"


def max_distance_legacy_timestamp(distances: list[tuple[float, datetime]]) -> str:
    """Return the legacy timestamp associated with the largest finite distance."""
    finite_distances = (item for item in distances if math.isfinite(item[0]))
    largest = max(finite_distances, key=lambda item: item[0], default=None)
    return largest[1].isoformat().replace("+00:00", "Z") if largest else "nan"


def format_summary_table(rows: list[tuple[str, ...]]) -> str:
    """Return summary rows as one aligned, fixed-width plain-text table."""
    if any(len(row) != len(SUMMARY_COLUMNS) for row in rows):
        raise ValueError(f"summary rows must contain {len(SUMMARY_COLUMNS)} values")
    text_rows = [SUMMARY_COLUMNS, *(tuple(str(value) for value in row) for row in rows)]
    widths = [max(len(row[index]) for row in text_rows) for index in range(len(SUMMARY_COLUMNS))]

    def format_row(row: tuple[str, ...]) -> str:
        cells = [
            value.ljust(widths[index]) if index in LEFT_ALIGNED_COLUMNS else value.rjust(widths[index])
            for index, value in enumerate(row)
        ]
        return "  ".join(cells)

    header = format_row(SUMMARY_COLUMNS)
    return "\n".join((header, "-" * len(header), *(format_row(row) for row in text_rows[1:])))


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


def write_unmatched_times(
    path: Path,
    unmatched_times: list[datetime],
    log_events: list[tuple[datetime, str]],
    mer_events: list[tuple[datetime, str]],
) -> None:
    lines = [UNMATCHED_HEADER]
    for legacy_time in unmatched_times:
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
    parser.add_argument("tables", nargs="?", type=Path, help="directory containing generated *_all.txt tables")
    parser.add_argument("-i", "--input", dest="input_tables", type=Path, help="alternative to the TABLES positional argument")
    parser.add_argument(
        "--legacy",
        type=Path,
        default=Path("~/mermaid/esoloc"),
        help="directory containing legacy *_all.txt tables (default: %(default)s)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="write the plain-text comparison log to this file (default: stdout only)",
    )
    parser.add_argument(
        "--records",
        type=Path,
        default=Path("~/mermaid/records"),
        help="normalized records root used to find bracketing source files (default: %(default)s)",
    )
    parser.add_argument(
        "--unmatched-output",
        type=Path,
        help="directory for per-float unmatched-time files (default: beside OUTPUT, or TABLES)",
    )
    parser.add_argument(
        "--match-seconds",
        type=int,
        default=300,
        help="maximum offset for a legacy row to count as matched (default: %(default)s)",
    )
    parser.add_argument("--instruments", nargs="*", help="limit comparison to station IDs")
    args = parser.parse_args()
    if args.tables is not None and args.input_tables is not None:
        parser.error("TABLES and --input cannot be used together")
    args.tables = args.tables or args.input_tables
    if args.tables is None:
        parser.error("a tables directory is required (TABLES or --input)")
    return args


def main() -> None:
    args = parse_args()
    unmatched_output = args.unmatched_output
    if unmatched_output is None:
        unmatched_output = args.output.parent if args.output else args.tables
    unmatched_output = unmatched_output.expanduser()
    unmatched_output.mkdir(parents=True, exist_ok=True)
    records_root = args.records.expanduser()
    if not records_root.is_dir():
        raise SystemExit(f"normalized records root is not a directory: {records_root}")
    record_directories = station_directories(records_root)
    lines = [
        "eso_locations comparison",
        "",
        f"Tables: {args.tables.resolve()}",
        f"Untrusted derived comparison set: {args.legacy.expanduser().resolve()}",
        f"Normalized records: {records_root.resolve()}",
        f"Unmatched-time files: {unmatched_output.resolve()}",
        "",
        "The normalized-record product is authoritative; this is a difference log, not a pass/fail test.",
        "",
        f"A legacy row with no normalized GPS row within {args.match_seconds} seconds is flagged as unmatched.",
        "",
    ]
    summary_rows = []
    legacy_root = args.legacy.expanduser()
    names = {x.name for x in args.tables.glob("*_all.txt")} | {x.name for x in legacy_root.glob("*_all.txt")}
    if args.instruments:
        wanted = {f"{station}_all.txt" for station in args.instruments}
        names &= wanted
    for name in sorted(names):
        station = name.removesuffix("_all.txt")
        generated = read_rows(args.tables / name)
        legacy = read_rows(legacy_root / name)
        offsets = []
        distances = []
        unmatched = 0
        unmatched_times = []
        for row in legacy:
            match = nearest(row, generated)
            offset = abs((match[0] - row[0]).total_seconds()) if match else None
            if match is not None and offset is not None and offset <= args.match_seconds:
                offsets.append(offset)
                distances.append((distance_m(row, match), row[0]))
            else:
                unmatched += 1
                unmatched_times.append(row[0])
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
        write_unmatched_times(
            unmatched_output / f"{station}_unmatched_time.txt",
            unmatched_times,
            log_events,
            mer_events,
        )
        summary_rows.append(
            (
                station,
                str(len(generated)),
                str(len(legacy)),
                f"{len(generated) - len(legacy):+d}",
                str(len(legacy) - unmatched),
                str(unmatched),
                median(offsets),
                median([distance for distance, _ in distances]),
                max_distance_legacy_timestamp(distances),
            )
        )
    lines.append(format_summary_table(summary_rows))
    text = "\n".join(lines) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
