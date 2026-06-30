#!/usr/bin/env python3
"""Build fixed-width per-float tables from normalized mermaid-records JSONL."""

from __future__ import annotations

import argparse
import bisect
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


LOG_COORD = re.compile(r"([NSEW])(\d+)deg([\d.]+)mn", re.I)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class Event:
    time: datetime
    source: str
    values: tuple
    family: str = "log"
    preference: int = 0


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


def record_timestamp(row: dict, field: str = "record_time") -> datetime | None:
    try:
        return timestamp(row.get(field))
    except ValueError:
        return None


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


def gps_events(directory: Path) -> tuple[str, list[Event]]:
    station = ""
    positions: list[Event] = []
    for row in records(directory, "log_gps_records") or ():
        station = row.get("instrument_id") or station
        time = record_timestamp(row)
        raw = row.get("raw_values") or {}
        if time and row.get("gps_record_kind") == "fix_position":
            positions.append(
                Event(
                    time,
                    row.get("source_file") or "",
                    (log_coordinate(raw["latitude"]), log_coordinate(raw["longitude"])),
                    "log_gps_records",
                )
            )

    for row in records(directory, "mer_environment_records") or ():
        station = row.get("instrument_id") or station
        if row.get("environment_kind") != "gpsinfo":
            continue
        time = record_timestamp(row, "gpsinfo_date")
        raw = row.get("raw_values") or {}
        if time and raw.get("lat") is not None and raw.get("lon") is not None:
            positions.append(
                Event(
                    time,
                    row.get("source_file") or "",
                    (mer_coordinate(raw["lat"]), mer_coordinate(raw["lon"])),
                    "mer_environment_records",
                )
            )
    return station, sorted(positions, key=lambda x: x.time)


def dop_events(directory: Path) -> list[Event]:
    result = []
    for row in records(directory, "log_gps_records") or ():
        if row.get("gps_record_kind") != "dop":
            continue
        time = record_timestamp(row)
        raw = row.get("raw_values") or {}
        if time and raw.get("hdop") is not None and raw.get("vdop") is not None:
            result.append(Event(time, row.get("source_file") or "", (float(raw["hdop"]), float(raw["vdop"])), "log_gps_records"))
    return sorted(result, key=lambda x: x.time)


def battery_events(directory: Path) -> list[Event]:
    result = []
    for row in records(directory, "log_battery_records") or ():
        time = record_timestamp(row)
        voltage = row.get("voltage_mv")
        if voltage is None or not time:
            continue
        preference = 0 if row.get("battery_record_kind") == "vbat_summary" else 1
        result.append(
            Event(
                time,
                row.get("source_file") or "",
                (int(voltage), as_optional_int(row.get("minimum_voltage_mv"))),
                "log_battery_records",
                preference,
            )
        )
    return sorted(result, key=lambda x: x.time)


def pressure_events(directory: Path) -> tuple[list[Event], list[Event]]:
    internal = []
    external = []
    for row in records(directory, "log_pressure_temperature_records") or ():
        time = record_timestamp(row)
        if not time:
            continue
        source = row.get("source_file") or ""
        if row.get("internal_pressure_pa") is not None:
            internal.append(Event(time, source, (int(row["internal_pressure_pa"]),), "log_pressure_temperature_records"))
        if row.get("external_pressure_mbar") is not None:
            external.append(
                Event(
                    time,
                    source,
                    (int(row["external_pressure_mbar"]), as_optional_int(row.get("external_pressure_range_mbar"))),
                    "log_pressure_temperature_records",
                )
            )
    return sorted(internal, key=lambda x: x.time), sorted(external, key=lambda x: x.time)


def iridium_events(directory: Path) -> tuple[list[Event], list[Event]]:
    commands = []
    uploads = []
    for row in records(directory, "log_iridium_records") or ():
        for event in row.get("iridium_events") or (row,):
            kind = event.get("iridium_event_kind") or event.get("transmission_kind")
            source_event = dict(row)
            source_event.update(event)
            try:
                time = timestamp(source_event.get("record_time"))
            except ValueError:
                time = None
            source = event.get("source_file") or row.get("source_file") or ""
            if not time:
                continue
            command_count = first_present(event, "received_command_count", "n_commands_received", "command_count")
            upload_count = first_present(event, "uploaded_file_count", "n_files_uploaded")
            if kind == "command_summary" and command_count is not None:
                commands.append(Event(time, source, (int(command_count),), "log_iridium_records"))
            elif kind == "upload_session_summary" and upload_count is not None:
                uploads.append(Event(time, source, (int(upload_count),), "log_iridium_records"))
    return sorted(commands, key=lambda x: x.time), sorted(uploads, key=lambda x: x.time)


def first_present(mapping: dict, *keys: str) -> object | None:
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def as_optional_int(value: object | None) -> int | None:
    return int(value) if value is not None else None


def one_to_one_matches(
    anchors: list[Event],
    candidates: list[Event],
    seconds: int,
    anchor_family: str | None = None,
) -> list[Event | None]:
    result: list[Event | None] = [None] * len(anchors)
    if not anchors or not candidates:
        return result
    candidate_times = [candidate.time.timestamp() for candidate in candidates]
    pairs = []
    for anchor_index, anchor in enumerate(anchors):
        if anchor_family and anchor.family != anchor_family:
            continue
        start = bisect.bisect_left(candidate_times, anchor.time.timestamp() - seconds)
        stop = bisect.bisect_right(candidate_times, anchor.time.timestamp() + seconds)
        for candidate_index in range(start, stop):
            candidate = candidates[candidate_index]
            offset = abs((candidate.time - anchor.time).total_seconds())
            source_penalty = 0 if candidate.source == anchor.source else 1
            pairs.append((candidate.preference, source_penalty, offset, anchor_index, candidate_index))
    used_anchors: set[int] = set()
    used_candidates: set[int] = set()
    for _, _, _, anchor_index, candidate_index in sorted(pairs):
        if anchor_index in used_anchors or candidate_index in used_candidates:
            continue
        result[anchor_index] = candidates[candidate_index]
        used_anchors.add(anchor_index)
        used_candidates.add(candidate_index)
    return result


def format_time(value: datetime) -> str:
    return f"{value.day:02d}-{MONTHS[value.month - 1]}-{value.year:04d} {value:%H:%M:%S}"


def fmt_float(value: float | None, width: int, precision: int) -> str:
    return f"{'NaN':>{width}s}" if value is None else f"{value:{width}.{precision}f}"


def fmt_int(value: int | None, width: int) -> str:
    return f"{'NaN':>{width}s}" if value is None else f"{value:{width}d}"


def format_row(station: str, gps: Event, dop: Event | None, battery: Event | None, internal: Event | None, external: Event | None, command: Event | None, upload: Event | None) -> str:
    lat, lon = gps.values
    hdop, vdop = dop.values if dop else (None, None)
    battery_mv, minimum = battery.values if battery else (None, None)
    internal_pressure = internal.values[0] if internal else None
    external_pressure, pressure_range = external.values if external else (None, None)
    commands = command.values[0] if command else None
    uploaded = upload.values[0] if upload else None
    return (
        f"{station:<5s}   {format_time(gps.time)}  {lat:11.6f} {lon:12.6f} "
        f"{fmt_float(hdop, 7, 3)}{fmt_float(vdop, 7, 3)}   {fmt_int(battery_mv, 6)} {fmt_int(minimum, 6)}   {fmt_int(internal_pressure, 6)}"
        f"{fmt_int(external_pressure, 6)}{fmt_int(pressure_range, 5)}   {fmt_int(commands, 3)} {'NaN':>3s} {fmt_int(uploaded, 3)}"
    )


def audit_row(station: str, index: int, gps: Event, dop: Event | None, battery: Event | None, internal: Event | None, external: Event | None, command: Event | None, upload: Event | None) -> dict:
    def joined(event: Event | None, columns: list[str], family: str) -> dict:
        values = dict(zip(columns, event.values)) if event else {column: None for column in columns}
        statuses = {column: "matched" if value is not None else "missing" for column, value in values.items()}
        if event is None:
            return {"status": "missing", "field_status": statuses, "family": family, "values": values}
        return {
            "status": "matched",
            "field_status": statuses,
            "family": family,
            "values": values,
            "source_file": event.source,
            "record_time": event.time.isoformat().replace("+00:00", "Z"),
            "offset_seconds": int((event.time - gps.time).total_seconds()),
        }

    return {
        "row_number": index,
        "anchor": {
            "status": "observed",
            "family": gps.family,
            "source_file": gps.source,
            "record_time": gps.time.isoformat().replace("+00:00", "Z"),
            "values": {"station": station, "datetime": format_time(gps.time), "lat": gps.values[0], "lon": gps.values[1]},
        },
        "dop": joined(dop, ["hdop", "vdop"], "log_gps_records"),
        "battery": joined(battery, ["battery_mv", "min_voltage_mv"], "log_battery_records"),
        "internal_pressure": joined(internal, ["internal_pressure_pa"], "log_pressure_temperature_records"),
        "external_pressure": joined(external, ["external_pressure_mbar", "pressure_range_mbar"], "log_pressure_temperature_records"),
        "commands": joined(command, ["n_commands_received"], "log_iridium_records"),
        "queued": {"status": "missing", "family": None, "values": {"n_files_queued": None}, "reason": "not normalized"},
        "uploaded": joined(upload, ["n_files_uploaded"], "log_iridium_records"),
    }


def station_from_directory(directory: Path) -> str:
    match = re.search(r"-([A-Z])-(\d+)$", directory.name)
    return f"{match.group(1)}{int(match.group(2)):04d}" if match else directory.name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-i",
        "--root",
        type=Path,
        default=Path("~/mermaid/records"),
        help="normalized records root (default: %(default)s)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("tables"),
        help="directory for generated fixed-width tables (default: %(default)s)",
    )
    parser.add_argument("--audit-output", type=Path, help="audit directory (default: OUTPUT/audit)")
    parser.add_argument("--instruments", nargs="*", help="station IDs or normalized instrument directory names")
    parser.add_argument(
        "--dop-seconds",
        type=int,
        default=300,
        help="maximum DOP-to-position join offset (default: %(default)s)",
    )
    parser.add_argument(
        "--vital-seconds",
        type=int,
        default=300,
        help="maximum battery/pressure-to-position join offset (default: %(default)s)",
    )
    parser.add_argument(
        "--status-seconds",
        type=int,
        default=300,
        help="maximum command/upload-to-position join offset (default: %(default)s)",
    )
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
        station, positions = gps_events(directory)
        station = station or station_from_directory(directory)
        if not positions:
            continue
        dops = one_to_one_matches(positions, dop_events(directory), args.dop_seconds, anchor_family="log_gps_records")
        batteries = one_to_one_matches(positions, battery_events(directory), args.vital_seconds)
        internal_pressures, external_pressures = pressure_events(directory)
        internal_matches = one_to_one_matches(positions, internal_pressures, args.vital_seconds)
        external_matches = one_to_one_matches(positions, external_pressures, args.vital_seconds)
        commands, uploads = iridium_events(directory)
        command_matches = one_to_one_matches(positions, commands, args.status_seconds)
        upload_matches = one_to_one_matches(positions, uploads, args.status_seconds)
        rows = []
        audit = []
        for index, gps in enumerate(positions, 1):
            matched = (
                dops[index - 1],
                batteries[index - 1],
                internal_matches[index - 1],
                external_matches[index - 1],
                command_matches[index - 1],
                upload_matches[index - 1],
            )
            rows.append(format_row(station, gps, *matched))
            audit.append(audit_row(station, index, gps, *matched))
        (args.output / f"{station}_all.txt").write_text("\n".join(rows) + "\n", encoding="ascii")
        with (audit_output / f"{station}_all.jsonl").open("w", encoding="utf-8") as handle:
            for item in audit:
                handle.write(json.dumps(item, separators=(",", ":")) + "\n")
        print(
            f"{station}: rows={len(rows)} dop={sum(x is not None for x in dops)} "
            f"battery={sum(x is not None for x in batteries)} internal={sum(x is not None for x in internal_matches)} "
            f"external={sum(x is not None for x in external_matches)} commands={sum(x is not None for x in command_matches)} "
            f"uploads={sum(x is not None for x in upload_matches)}"
        )


if __name__ == "__main__":
    main()
