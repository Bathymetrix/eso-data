from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import compare_esoloc as compare


UTC = timezone.utc


def test_median_uses_nan_for_missing_or_nonfinite_values() -> None:
    assert compare.median([]) == "nan"
    assert compare.median([1.0, float("nan"), 3.0]) == "nan"
    assert compare.median([1.0, 3.0]) == "2.0"


def test_surrounding_files_uses_strict_neighbors() -> None:
    events = [
        (datetime(2024, 1, 1, 0, 0, tzinfo=UTC), "before.LOG"),
        (datetime(2024, 1, 1, 0, 5, tzinfo=UTC), "exact.LOG"),
        (datetime(2024, 1, 1, 0, 10, tzinfo=UTC), "after.LOG"),
    ]

    assert compare.surrounding_files(events, datetime(2024, 1, 1, 0, 5, tzinfo=UTC)) == (
        "before.LOG",
        "after.LOG",
    )


def test_write_unmatched_times_writes_one_row_per_timestamp(tmp_path: Path) -> None:
    legacy_time = datetime(2024, 1, 1, 0, 5, tzinfo=UTC)
    output = tmp_path / "P0001_unmatched_time.txt"

    compare.write_unmatched_times(
        output,
        [legacy_time],
        [
            (datetime(2024, 1, 1, 0, 0, tzinfo=UTC), "before.LOG"),
            (datetime(2024, 1, 1, 0, 10, tzinfo=UTC), "after.LOG"),
        ],
        [
            (datetime(2023, 12, 31, 23, 55, tzinfo=UTC), "before.MER"),
            (datetime(2024, 1, 1, 0, 15, tzinfo=UTC), "after.MER"),
        ],
    )

    assert output.read_text(encoding="utf-8").splitlines() == [
        compare.UNMATCHED_HEADER,
        "2024-01-01T00:05:00Z\tbefore.LOG\tafter.LOG\tbefore.MER\tafter.MER",
    ]


def test_format_summary_table_uses_fixed_width_alignment() -> None:
    rows = [
        ("N0001", "3346", "844", "+2502", "834", "10", "53.0", "0.0", "2021-12-07T22:14:03Z"),
        ("N0002", "18", "36", "-18", "31", "5", "nan", "nan", "nan"),
    ]

    table = compare.format_summary_table(rows)

    assert table.splitlines() == [
        "Instrument  Generated  Legacy  Delta  Legacy matched  Legacy unmatched  Matched median abs(dt) (s)  Matched median distance (m)  Max matched distance legacy timestamp",
        "----------------------------------------------------------------------------------------------------------------------------------------------------------------------",
        "N0001            3346     844  +2502             834                10                        53.0                          0.0  2021-12-07T22:14:03Z                 ",
        "N0002              18      36    -18              31                 5                         nan                          nan  nan                                  ",
    ]
    assert "|" not in table


def test_max_distance_legacy_timestamp_ignores_nonfinite_distances() -> None:
    earlier = datetime(2024, 1, 1, tzinfo=UTC)
    later = datetime(2024, 1, 2, tzinfo=UTC)

    assert compare.max_distance_legacy_timestamp(
        [(float("nan"), earlier), (12.0, earlier), (15.0, later)]
    ) == "2024-01-02T00:00:00Z"
    assert compare.max_distance_legacy_timestamp([(float("nan"), earlier)]) == "nan"
