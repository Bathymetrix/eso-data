from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import compare_esoloc as compare


UTC = timezone.utc


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


def test_write_uncovered_times_writes_one_row_per_timestamp(tmp_path: Path) -> None:
    legacy_time = datetime(2024, 1, 1, 0, 5, tzinfo=UTC)
    output = tmp_path / "P0001_uncovered_time.txt"

    compare.write_uncovered_times(
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
        compare.UNCOVERED_HEADER,
        "2024-01-01T00:05:00Z\tbefore.LOG\tafter.LOG\tbefore.MER\tafter.MER",
    ]
