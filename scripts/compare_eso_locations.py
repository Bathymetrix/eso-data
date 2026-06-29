#!/usr/bin/env python3
"""Compare generated tables with eso_locations and write a Markdown log."""

from __future__ import annotations

import argparse
import bisect
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated", type=Path)
    parser.add_argument("--legacy", type=Path, default=Path("~/mermaid/esoloc").expanduser())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--coverage-seconds", type=int, default=3600)
    parser.add_argument("--instruments", nargs="*", help="limit comparison to station IDs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lines = [
        "# eso_locations comparison",
        "",
        f"Generated: `{args.generated.resolve()}`",
        f"Untrusted derived comparison set: `{args.legacy.expanduser().resolve()}`",
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
