EarthScope-Oceans Data Products

Small tools for generating public per-float location/status tables from
normalized mermaid-records JSONL outputs.

Current version: 0.1.0

The raw source files under ~/mermaid/server_everyone/ are the source of truth
for input data. Build tables from a normalized JSONL output produced from a
known mermaid-records run over that raw input. The current default normalized
output location, ~/mermaid/records/, is in flux and should not be treated as a
stable baseline comparator against ~/mermaid/esoloc/. This repo reads
normalized JSONL only and never parses raw MERMAID files directly.

Generate Tables

./scripts/build_location_tables.py --output tables

Pass --root to the normalized JSONL root you want to publish from. The builder
currently consumes these normalized record families:

log_gps_records
log_battery_records
log_pressure_temperature_records
log_iridium_records

It writes:

tables/P0023_all.txt
tables/P0050_all.txt
tables/audit/P0023_all.jsonl
tables/audit/P0050_all.jsonl

Each *_all.txt file uses the same 15-column fixed-width shape as the
historical VIT2TBL products:

station datetime lat lon hdop vdop battery_mv min_voltage_mv internal_pressure_pa external_pressure_mbar pressure_range_mbar n_commands_received n_files_queued n_files_uploaded

Rows are anchored on GPS fix_position observations. Latitude and longitude
are converted from the source GPS strings. DOP observations, battery telemetry,
pressure telemetry, and Iridium command/upload summaries are joined to the GPS
rows using bounded nearest-neighbor matching.

Status observations are consumed at most once. A battery, pressure, DOP,
command summary, or upload summary may be matched to only a single GPS row. If
multiple GPS fixes are nearby, the observation is assigned only to the nearest
GPS anchor and is not duplicated into neighboring rows. This preserves the
native cadence of each underlying telemetry stream.

The primary text files contain only public table rows. Their JSONL sidecars
record the source family, source file, source timestamp, join offset, emitted
values, match status, and provenance for every emitted value.

Missing values are written as `NaN`, regardless of type or display precision.

`n_files_queued` is currently unavailable from normalized records and is
therefore always emitted as `NaN`.

To generate selected instruments:

./scripts/build_location_tables.py \
  --output tables \
  --instruments P0023 P0050

Useful options:

--root PATH             normalized records root
--audit-output PATH     separate audit-sidecar directory
--dop-seconds N         maximum DOP join offset (default: 300)
--vital-seconds N       maximum battery/pressure join offset (default: 3600)
--status-seconds N      maximum Iridium command/upload join offset (default: 1800)

Install Development Dependencies

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

Run Tests

python -m pytest

Compare Historical Output

~/mermaid/esoloc/ is a legacy derived product of unknown provenance. It is
used only as a diagnostic comparison and is never used to populate output
tables.

./scripts/compare_eso_locations.py tables \
  --output reports/eso_locations_comparison.md

The report summarizes row counts, nearest timestamp and position differences,
vital-field agreement, and legacy rows with no normalized GPS observation
within the comparison window.

Inspect Inputs

./scripts/inspect_vit2tbl_inputs.py

This read-only discovery tool summarizes normalized record families, sampled
fields, and timestamp alignment diagnostics. Use --all to inspect every
instrument.

Design

See docs/vit2tbl_product_design.md for the
column mappings, GPS row-anchor policy, join strategy, missing-data contract,
and known limitations.

The production scripts currently use the Python standard library. Development
and regression tests use the dependencies listed in requirements-dev.txt.
