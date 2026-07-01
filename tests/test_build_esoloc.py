from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_esoloc as tables


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")


def test_negative_log_epoch_components_do_not_suppress_corrected_gps_anchor(tmp_path: Path) -> None:
    instrument = tmp_path / "452.020-P-25"
    instrument.mkdir()

    write_jsonl(
        instrument / "log_gps_records.452.020-P-25.jsonl",
        [
            {
                "instrument_id": "P0025",
                "source_file": "25_8929BED9.LOG",
                "gps_record_kind": "gps_ack",
                "log_epoch_time": -1993752681,
                "record_time": "1906-10-13T23:08:39.000000Z",
                "raw_values": {},
            },
            {
                "instrument_id": "P0025",
                "source_file": "25_8929BED9.LOG",
                "gps_record_kind": "gps_off",
                "log_epoch_time": -1993752671,
                "record_time": "1906-10-13T23:08:49.000000Z",
                "raw_values": {},
            },
            {
                "instrument_id": "P0025",
                "source_file": "25_8929BED9.LOG",
                "gps_record_kind": "fix_position",
                "log_epoch_time": 1681899427,
                "record_time": "2023-04-19T10:17:07.000000Z",
                "raw_values": {"latitude": "S23deg29.970mn", "longitude": "W132deg30.444mn"},
            },
            {
                "instrument_id": "P0025",
                "source_file": "25_8929BED9.LOG",
                "gps_record_kind": "dop",
                "log_epoch_time": 1681899427,
                "record_time": "2023-04-19T10:17:07.000000Z",
                "raw_values": {"hdop": "0.920", "vdop": "1.590"},
            },
        ],
    )
    write_jsonl(
        instrument / "log_iridium_records.452.020-P-25.jsonl",
        [
            {
                "instrument_id": "P0025",
                "source_file": "25_8929BED9.LOG",
                "log_epoch_time": -1993752671,
                "record_time": "1906-10-13T23:08:49.000000Z",
                "iridium_events": [
                    {
                        "iridium_event_kind": "command_summary",
                        "log_epoch_time": -1993752671,
                        "record_time": "1906-10-13T23:08:49.000000Z",
                        "received_command_count": 1,
                    },
                    {
                        "iridium_event_kind": "upload_session_summary",
                        "record_time": "2023-04-19T10:32:27.000000Z",
                        "uploaded_file_count": 1,
                    },
                ],
            },
        ],
    )

    station, positions = tables.gps_events(instrument)
    dops = tables.dop_events(instrument)
    commands, uploads = tables.iridium_events(instrument)

    assert station == "P0025"
    assert len(positions) == 1
    assert int(positions[0].time.timestamp()) == 1681899427
    assert positions[0].values == (-23.4995, -132.5074)
    assert len(dops) == 1
    assert dops[0].values == (0.920, 1.590)
    assert len(commands) == 1
    assert len(uploads) == 1

    command_matches = tables.one_to_one_matches(positions, commands, 1800)
    upload_matches = tables.one_to_one_matches(positions, uploads, 1800)

    assert command_matches == [None]
    assert upload_matches[0] is not None


def test_dop_matching_never_uses_observation_before_gps_anchor() -> None:
    first = tables.Event(
        tables.timestamp("2018-06-27T19:15:33Z"),
        "06_5B32904C.LOG",
        (-14.453333, -179.485017),
        "log_gps_records",
    )
    second = tables.Event(
        tables.timestamp("2018-06-27T19:16:33Z"),
        "06_5B32904C.LOG",
        (-14.453400, -179.485033),
        "log_gps_records",
    )
    dop = tables.Event(
        tables.timestamp("2018-06-27T19:16:23Z"),
        "06_5B32904C.LOG",
        (0.600, 0.920),
        "log_gps_records",
    )

    matches = tables.one_to_one_matches(
        [first, second],
        [dop],
        300,
        anchor_family="log_gps_records",
        candidate_not_before_anchor=True,
    )

    assert matches == [dop, None]
