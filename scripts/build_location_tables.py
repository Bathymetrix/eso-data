#!/usr/bin/env python3
"""Build fixed-width per-float tables from normalized mermaid-records JSONL."""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


VBAT = re.compile(r"\bVbat\s+(-?\d+)mV\s+\(min\s+(-?\d+)mV\)", re.I)
PINT = re.compile(r"\b(?:Pint|internal pressure)\s+(-?\d+)Pa\b", re.I)
PEXT = re.compile(r"\bPext\s*([+-]?\d+)mbar\s+\(rng\s+(-?\d+)\s*mbar\)", re.I)
COMMAND = re.compile(r"^(\d+)\s+cmd\(s\) received$", re.I)
LOG_COORD = re.compile(r"([NSEW])(\d+)deg([\d.]+)mn", re.I)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Event:
    time: datetime
    source: str
    values: tuple
    family: str = "log"
    equivalents: tuple[tuple[str, str, str], ...] = ()


def records(directory: Path, family: str):
    paths = sorted(directory.glob(f"{family}.*.jsonl"))
    if not paths:
        return
    with paths[0].open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def log_coordinate(value: str) -> float:
    match = LOG_COORD.fullmatch(value)
    if not match:
        raise ValueError(f"unrecognized LOG coordinate: {value!r}")
    hemisphere, degrees, minutes = match.groups()
    result = int(degrees) + float(minutes) / 60.0
    return -result if hemisphere.upper() in "SW" else result


def mer_coordinate(value: str) -> float:
    raw = float(value)
    sign = -1 if raw < 0 else 1
    raw = abs(raw)
    degrees = int(raw // 100)
    return sign * (degrees + (raw - degrees * 100) / 60.0)


def distance_m(a: Event, b: Event) -> float:
    lat1, lon1 = map(math.radians, a.values[:2])
    lat2, lon2 = map(math.radians, b.values[:2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 12_742_000 * math.asin(math.sqrt(h))


def gps_events(directory: Path) -> tuple[str, list[Event], int]:
    station = ""
    dops: dict[tuple[str, datetime], tuple[float, float]] = {}
    fixes: list[Event] = []
    for row in records(directory, "log_gps_records") or ():
        station = row.get("instrument_id") or station
        time = timestamp(row.get("record_time"))
        source = row.get("source_file") or ""
        raw = row.get("raw_values") or {}
        if not time:
            continue
        if row.get("gps_record_kind") == "dop":
            dops[(source, time)] = (float(raw["hdop"]), float(raw["vdop"]))
        elif row.get("gps_record_kind") == "fix_position":
            fixes.append(Event(time, source, (log_coordinate(raw["latitude"]), log_coordinate(raw["longitude"])), "log_gps_records"))

    log_positions = [Event(x.time, x.source, x.values + dops.get((x.source, x.time), (-1.0, -1.0)), x.family) for x in fixes]
    log_positions = list({(x.time, x.values[0], x.values[1]): x for x in log_positions}.values())
    log_times = [x.time for x in sorted(log_positions, key=lambda x: x.time)]
    sorted_logs = sorted(log_positions, key=lambda x: x.time)

    mer_positions: list[Event] = []
    for row in records(directory, "mer_environment_records") or ():
        station = row.get("instrument_id") or station
        if row.get("environment_kind") != "gpsinfo":
            continue
        time = timestamp(row.get("gpsinfo_date"))
        raw = row.get("raw_values") or {}
        if time and raw.get("lat") is not None and raw.get("lon") is not None:
            mer_positions.append(Event(time, row.get("source_file") or "", (mer_coordinate(raw["lat"]), mer_coordinate(raw["lon"]), -1.0, -1.0), "mer_environment_records"))
    mer_positions = list({(x.time, x.values[0], x.values[1]): x for x in mer_positions}.values())

    mer_only = []
    for item in mer_positions:
        index = bisect.bisect_left(log_times, item.time)
        nearby = sorted_logs[max(0, index - 2) : index + 2]
        duplicates = [
            other
            for other in nearby
            if abs((item.time - other.time).total_seconds()) <= 90 and distance_m(item, other) <= 500
        ]
        if duplicates:
            match = min(duplicates, key=lambda other: abs((item.time - other.time).total_seconds()))
            match_index = sorted_logs.index(match)
            equivalent = (item.family, item.source, item.time.isoformat().replace("+00:00", "Z"))
            sorted_logs[match_index] = Event(
                match.time,
                match.source,
                match.values,
                match.family,
                match.equivalents + (equivalent,),
            )
        else:
            mer_only.append(item)
    return station, sorted(sorted_logs + mer_only, key=lambda x: x.time), len(mer_only)


def operational_events(directory: Path) -> tuple[list[Event], list[Event]]:
    by_source: dict[str, list[tuple[datetime, str]]] = {}
    commands = []
    for row in records(directory, "log_operational_records") or ():
        time = timestamp(row.get("record_time"))
        source = row.get("source_file") or ""
        message = str(row.get("message") or "")
        if not time:
            continue
        by_source.setdefault(source, []).append((time, message))
        match = COMMAND.fullmatch(message)
        if match:
            commands.append(Event(time, source, (int(match.group(1)),)))

    vitals = []
    for source, rows in by_source.items():
        rows.sort()
        times = [time for time, _ in rows]
        for time, message in rows:
            match = VBAT.search(message)
            if not match:
                continue
            start = bisect.bisect_left(times, time.timestamp() - 10, key=lambda x: x.timestamp())
            stop = bisect.bisect_right(times, time.timestamp() + 10, key=lambda x: x.timestamp())
            nearby = rows[start:stop]
            pint = next((PINT.search(text) for _, text in nearby if PINT.search(text)), None)
            pext = next((PEXT.search(text) for _, text in nearby if PEXT.search(text)), None)
            if pint and pext:
                vitals.append(Event(time, source, tuple(map(int, match.groups() + pint.groups() + pext.groups()))))
    return sorted(vitals, key=lambda x: x.time), sorted(commands, key=lambda x: x.time)


def upload_events(directory: Path) -> list[Event]:
    result = []
    for row in records(directory, "log_transmission_records") or ():
        value = row.get("uploaded_file_count")
        time = timestamp(row.get("record_time"))
        if value is not None and time:
            result.append(Event(time, row.get("source_file") or "", (int(value),)))
    return sorted(result, key=lambda x: x.time)


def nearest(anchor: Event, candidates: list[Event], seconds: int) -> Event | None:
    eligible = [x for x in candidates if abs((x.time - anchor.time).total_seconds()) <= seconds]
    if not eligible:
        return None
    same_source = [x for x in eligible if x.source == anchor.source]
    return min(same_source or eligible, key=lambda x: abs((x.time - anchor.time).total_seconds()))


def following(anchor: Event, candidates: list[Event], seconds: int) -> Event | None:
    eligible = [x for x in candidates if 0 <= (x.time - anchor.time).total_seconds() <= seconds]
    if not eligible:
        return None
    same_source = [x for x in eligible if x.source == anchor.source]
    return min(same_source or eligible, key=lambda x: x.time)


def format_time(value: datetime) -> str:
    return f"{value.day:02d}-{MONTHS[value.month - 1]}-{value.year:04d} {value:%H:%M:%S}"


def format_row(station: str, gps: Event, vital: Event | None, command: Event | None, upload: Event | None) -> str:
    battery, minimum, internal, external, pressure_range = vital.values if vital else (-1, -1, -1, -1, -1)
    commands = command.values[0] if command else -1
    uploaded = upload.values[0] if upload else -1
    lat, lon, hdop, vdop = gps.values
    return (
        f"{station:<5s}   {format_time(gps.time)}  {lat:11.6f} {lon:12.6f} "
        f"{hdop:7.3f}{vdop:7.3f}   {battery:6d} {minimum:6d}   {internal:6d}"
        f"{external:6d}{pressure_range:5d}   {commands:3d} {-1:3d} {uploaded:3d}"
    )


def audit_row(station: str, index: int, gps: Event, vital: Event | None, command: Event | None, upload: Event | None) -> dict:
    def joined(event: Event | None, columns: list[str], family: str) -> dict:
        if event is None:
            return {"status": "missing", "family": family, "values": {column: None for column in columns}}
        return {
            "status": "matched",
            "family": family,
            "values": dict(zip(columns, event.values)),
            "source_file": event.source,
            "record_time": event.time.isoformat().replace("+00:00", "Z"),
            "offset_seconds": int((event.time - gps.time).total_seconds()),
        }

    hdop_status = "observed" if gps.values[2] >= 0 else "missing"
    return {
        "row_number": index,
        "anchor": {
            "status": "observed",
            "family": gps.family,
            "source_file": gps.source,
            "record_time": gps.time.isoformat().replace("+00:00", "Z"),
            "values": {"station": station, "datetime": format_time(gps.time), "lat": gps.values[0], "lon": gps.values[1]},
            "equivalent_normalized_records": [
                {"family": family, "source_file": source, "record_time": time}
                for family, source, time in gps.equivalents
            ],
        },
        "dop": {
            "status": hdop_status,
            "family": "log_gps_records",
            "values": {
                "hdop": gps.values[2] if hdop_status == "observed" else None,
                "vdop": gps.values[3] if hdop_status == "observed" else None,
            },
            "source_file": gps.source if hdop_status == "observed" else None,
            "record_time": gps.time.isoformat().replace("+00:00", "Z") if hdop_status == "observed" else None,
        },
        "vital": joined(
            vital,
            ["battery_mv", "min_voltage_mv", "internal_pressure_pa", "external_pressure_mbar", "pressure_range_mbar"],
            "log_operational_records",
        ),
        "commands": joined(command, ["n_commands_received"], "log_operational_records"),
        "queued": {"status": "missing", "family": None, "values": {"n_files_queued": None}, "reason": "not normalized"},
        "uploaded": joined(upload, ["n_files_uploaded"], "log_transmission_records"),
    }


def station_from_directory(directory: Path) -> str:
    match = re.search(r"-([A-Z])-(\d+)$", directory.name)
    return f"{match.group(1)}{int(match.group(2)):04d}" if match else directory.name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("~/mermaid/records").expanduser())
    parser.add_argument("--output", type=Path, default=Path("tables"))
    parser.add_argument("--audit-output", type=Path, help="audit directory (default: OUTPUT/audit)")
    parser.add_argument("--instruments", nargs="*", help="station IDs or normalized instrument directory names")
    parser.add_argument("--vital-seconds", type=int, default=3600)
    parser.add_argument("--status-seconds", type=int, default=1800)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    wanted = set(args.instruments or ())
    directories = sorted(x for x in args.root.expanduser().iterdir() if x.is_dir())
    if wanted:
        directories = [x for x in directories if x.name in wanted or station_from_directory(x) in wanted]
    args.output.mkdir(parents=True, exist_ok=True)
    audit_output = args.audit_output or args.output / "audit"
    audit_output.mkdir(parents=True, exist_ok=True)
    for directory in directories:
        station, positions, mer_only = gps_events(directory)
        station = station or station_from_directory(directory)
        if not positions:
            continue
        vitals, commands = operational_events(directory)
        uploads = upload_events(directory)
        rows = []
        audit = []
        complete = 0
        for index, gps in enumerate(positions, 1):
            vital = nearest(gps, vitals, args.vital_seconds)
            command = nearest(gps, commands, args.status_seconds)
            upload = following(gps, uploads, args.status_seconds)
            complete += vital is not None
            rows.append(format_row(station, gps, vital, command, upload))
            audit.append(audit_row(station, index, gps, vital, command, upload))
        (args.output / f"{station}_all.txt").write_text("\n".join(rows) + "\n", encoding="ascii")
        with (audit_output / f"{station}_all.jsonl").open("w", encoding="utf-8") as handle:
            for item in audit:
                handle.write(json.dumps(item, separators=(",", ":")) + "\n")
        print(f"{station}: rows={len(rows)} log_gps={len(rows) - mer_only} mer_only={mer_only} complete_vitals={complete}")


if __name__ == "__main__":
    main()
