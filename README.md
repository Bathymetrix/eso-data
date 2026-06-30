# EarthScope-Oceans Data Products

Small tools for generating public per-float location/status tables from
normalized `mermaid-records` JSONL outputs.

**Current version:** 0.1.0

The raw source files under `~/mermaid/server_everyone/` are the source of truth
for input data. Build tables from normalized JSONL output produced by a known
`mermaid-records` run over that raw input.

The current default normalized output location, `~/mermaid/records/`, is in
flux and should not be treated as a stable baseline comparator against
`~/mermaid/esoloc/`. This repository reads normalized JSONL only; it never
parses raw MERMAID files directly.

## Generate Tables

```sh
./scripts/build_esoloc.py --output tables
```

Pass `--root` to select the normalized JSONL root to publish from. The builder
currently consumes these normalized record families:

- `log_gps_records`
- `log_battery_records`
- `log_pressure_temperature_records`
- `log_iridium_records`

It writes files such as:

```text
tables/P0023_all.txt
tables/P0050_all.txt
tables/audit/P0023_all.jsonl
tables/audit/P0050_all.jsonl
```

Each `*_all.txt` file uses the same fixed-width shape as the historical
VIT2TBL products:

|    # | Field                    |
| ---: | ------------------------ |
|    1 | `station`                |
|    2 | `datetime`               |
|    3 | `lat`                    |
|    4 | `lon`                    |
|    5 | `hdop`                   |
|    6 | `vdop`                   |
|    7 | `battery_mv`             |
|    8 | `min_voltage_mv`         |
|    9 | `internal_pressure_pa`   |
|   10 | `external_pressure_mbar` |
|   11 | `pressure_range_mbar`    |
|   12 | `n_commands_received`    |
|   13 | `n_files_queued`         |
|   14 | `n_files_uploaded`       |

The `datetime` value contains separate date and time components, so a row has
15 whitespace-delimited values.

Rows are anchored on GPS `fix_position` observations. Latitude and longitude
are converted from the source GPS strings. DOP observations, battery
telemetry, pressure telemetry, and Iridium command/upload summaries are joined
to GPS rows using bounded nearest-neighbor matching.

Status observations are consumed at most once. A battery, pressure, DOP,
command summary, or upload summary may be matched to only one GPS row. If
multiple GPS fixes are nearby, the observation is assigned to the nearest GPS
anchor and is not duplicated into neighboring rows. This preserves the native
cadence of each underlying telemetry stream.

The primary text files contain only public table rows. Their JSONL sidecars
record the source family, source file, source timestamp, join offset, emitted
values, match status, and provenance for every emitted value.

Missing values are written as `NaN`, regardless of type or display precision.
`n_files_queued` is currently unavailable from normalized records and is
therefore always emitted as `NaN`.

To generate selected instruments:

```sh
./scripts/build_esoloc.py \
  --output tables \
  --instruments P0023 P0050
```

Useful options:

| Option                   | Description                                               |
| ------------------------ | --------------------------------------------------------- |
| `--root PATH`            | Normalized records root                                   |
| `--audit-output PATH`    | Separate audit-sidecar directory                          |
| `--dop-seconds N`        | Maximum DOP join offset (default: 300)                    |
| `--vital-seconds N`      | Maximum battery/pressure join offset (default: 300)       |
| `--status-seconds N`     | Maximum Iridium command/upload join offset (default: 300) |

## Install Development Dependencies

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

## Run Tests

```sh
python -m pytest
```

## Compare Historical Output

`~/mermaid/esoloc/` is a legacy derived product of unknown provenance. It is
used only as a diagnostic comparison and is never used to populate output
tables.

```sh
./scripts/compare_esoloc.py tables \
  --output reports/eso_locations_comparison.md
```

The report summarizes row counts, nearest timestamp and position differences,
vital-field agreement, and legacy rows with no normalized GPS observation
within the comparison window.

## Inspect Inputs

```sh
./scripts/inspect_vit2tbl_inputs.py
```

This read-only discovery tool summarizes normalized record families, sampled
fields, and timestamp alignment diagnostics. Use `--all` to inspect every
instrument.

## Design

See [`docs/vit2tbl_product_design.md`](docs/vit2tbl_product_design.md) for the
column mappings, GPS row-anchor policy, join strategy, missing-data contract,
and known limitations.

The production scripts currently use the Python standard library. Development
and regression tests use the dependencies listed in `requirements-dev.txt`.
