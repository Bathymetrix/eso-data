# EarthScope-Oceans Data Products

Small tools for generating public per-float location/status tables from
normalized `mermaid-records` JSONL outputs.

The normalized records under `~/mermaid/records/` are the authoritative input.
Raw MERMAID files are not read or parsed.

## Generate Tables

```bash
./scripts/build_location_tables.py --output tables
```

This reads `~/mermaid/records/` by default and writes:

```text
tables/P0023_all.txt
tables/P0050_all.txt
tables/audit/P0023_all.jsonl
tables/audit/P0050_all.jsonl
```

Each `*_all.txt` file uses the same 15-column, 119-character fixed-width shape
as the historical VIT2TBL product:

```text
station datetime lat lon hdop vdop battery_mv min_voltage_mv internal_pressure_pa external_pressure_mbar pressure_range_mbar n_commands_received n_files_queued n_files_uploaded
```

The primary text files contain only public table rows. Their JSONL sidecars
record the source family, source file, source timestamp, join offset, emitted
values, and `observed`, `matched`, or `missing` status for every row.

Missing integers are written as `-1`; missing DOP values are `-1.000`.
`n_files_queued` is currently unavailable from normalized records and is
therefore always missing.

To generate selected instruments:

```bash
./scripts/build_location_tables.py \
  --output tables \
  --instruments P0023 P0050
```

Useful options:

```text
--root PATH             normalized records root
--audit-output PATH     separate audit-sidecar directory
--vital-seconds N       maximum vital-snapshot join offset (default: 3600)
--status-seconds N      command/upload join window (default: 1800)
```

## Compare Historical Output

`~/mermaid/esoloc/` is a derived product of unknown provenance. It is
not used to select or populate product rows. It is useful only as a diagnostic
comparison set.

```bash
./scripts/compare_eso_locations.py tables \
  --output reports/eso_locations_comparison.md
```

The report records row counts, nearest time and position differences, vital
tuple agreement, and legacy rows with no normalized-derived GPS observation
within one hour. The checked-in current report is
[reports/eso_locations_comparison.md](reports/eso_locations_comparison.md).

## Inspect Inputs

```bash
./scripts/inspect_vit2tbl_inputs.py
```

This read-only discovery tool prints JSONL family counts, sampled fields, and
timestamp-alignment diagnostics. Use `--all` to inspect every instrument.

## Design

See [docs/vit2tbl_product_design.md](docs/vit2tbl_product_design.md) for the
column mappings, GPS row-anchor policy, bounded temporal joins, missing-data
contract, and known ambiguities.

All scripts use only the Python standard library.
