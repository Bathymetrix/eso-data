# Public Float Table Design

## Authority And Scope

The product is derived only from normalized JSONL under
`~/mermaid/records/`. Those records are authoritative. The generated tables in
`~/mermaid/esoloc/` are useful comparison material, but they do not
decide row cadence or values.

The normalized families are asynchronous event streams. GPS, voltage,
pressure, command, and upload observations have different timestamps and row
counts. Joins must be temporal and provenance-aware, never by line number or
equal timestamp.

The implementation does not read raw LOG/VIT files and never modifies either
input directory.

## Relevant Normalized Families

Common provenance fields are `instrument_id`, `instrument_serial`,
`source_file`, `source_container`, and either `record_time`/`log_epoch_time` or
`gpsinfo_date`.

| Family | Relevant fields |
|---|---|
| `log_gps_records` | `gps_record_kind`, `raw_values.latitude`, `raw_values.longitude`, `raw_values.hdop`, `raw_values.vdop` |
| `mer_environment_records` | `environment_kind == "gpsinfo"`, `gpsinfo_date`, `raw_values.lat`, `raw_values.lon` |
| `log_operational_records` | messages containing `Vbat`, `Pint`, `Pext`, and `N cmd(s) received` |
| `log_transmission_records` | `transmission_kind`, `uploaded_file_count`, `record_time` |
| `log_battery_records` | individual voltage/current samples; not the board's legacy-style `Vbat ... (min ...)` snapshot |
| `log_pressure_temperature_records` | individual measurements; not the board's `Pext ... (rng ...)` snapshot |

Observed current-corpus overlap: `log_unclassified_records` is intended as a
separate family, but the `~/mermaid/records/` snapshot inspected for this
product contains byte-for-byte overlaps with `log_operational_records`. The
comparison key was `(source_file, record_time, raw_line)`. In that snapshot, 82
instruments had overlaps and every unclassified row in several instruments also
appeared in operational output. This looks like an upstream normalization issue
or stale generated output, not desired schema behavior. Until it is corrected,
the product reads legacy-style status messages from `log_operational_records`
only, otherwise the same raw LOG line can be joined twice.

Concrete duplicated examples from `452.020-P-0026`:

| Field group | Source/time | Raw line present in both families |
|---|---|---|
| `Vbat` | `0026_5D48EAB8.LOG`, `2019-08-07T02:57:30Z` | `1565146650:[MAIN  ,498]Vbat 14681mV (min 13967mV)` |
| internal pressure | `0026_5D3CDB8D.LOG`, `2019-07-27T23:17:41Z` | `1564269461:[MAIN  ,408]internal pressure 78680Pa` |
| `Pext` | `0026_5D48EAB8.LOG`, `2019-08-07T02:57:33Z` | `1565146653:[MAIN  ,507]Pext -45mbar (rng 30mbar)` |
| commands | `0026_5D48EAB8.LOG`, `2019-08-06T02:53:49Z` | `1565060029:[SURF  ,328]7 cmd(s) received` |

For these duplicated rows, the operational copy has `message_kind: raw` and
the unclassified copy has `unclassified_reason: no_family_match`.

## Column Mapping

| Output column | Normalized source and rule |
|---|---|
| `station` | GPS record `instrument_id` |
| `datetime` | GPS observation time in UTC, formatted `%d-%b-%Y %H:%M:%S` |
| `lat`, `lon` | LOG `fix_position`, plus MER `GPSINFO` observations not representing the same fix |
| `hdop`, `vdop` | exact same-source/time LOG `dop`; unknown for unmatched MER-only positions |
| `battery_mv`, `min_voltage_mv` | parse `Vbat NNNmV (min NNNmV)` |
| `internal_pressure_pa` | parse `Pint NNNPa` or `internal pressure NNNPa` |
| `external_pressure_mbar`, `pressure_range_mbar` | parse `Pext NNNmbar (rng NN mbar)` |
| `n_commands_received` | nearest numeric `N cmd(s) received` event within 30 minutes |
| `n_files_queued` | not present in current normalized outputs |
| `n_files_uploaded` | nearest following `upload_session_summary.uploaded_file_count` within 30 minutes |

## Row Anchor Policy

Emit one row per distinct normalized GPS observation:

1. Include every LOG `fix_position`.
2. Include every MER `GPSINFO` observation unless it matches a LOG observation
   within 90 seconds and 500 meters. In that case the two normalized records
   are treated as representations of one board observation and the LOG record
   is retained because it carries exact DOP provenance.
3. Deduplicate exact repeated records within a family by time and coordinates.

No GPS row is removed merely because voltage, pressure, command, or upload data
is sparse. This keeps row existence faithful to the normalized corpus rather
than to a historical product's filtering choices.

## Matching Policy

1. Pair LOG position and DOP by exact `(source_file, record_time)`.
2. Assemble a coherent vital snapshot from same-source `Vbat`, `Pint`, and
   `Pext` messages no more than 10 seconds apart. Match the snapshot as a unit;
   never select the five vital columns independently.
3. Match the nearest complete vital snapshot within one hour, preferring the
   same source file for LOG GPS observations.
4. Match the nearest command count within 30 minutes, again preferring the same
   source file.
5. Match the first upload summary after the GPS observation within 30 minutes,
   preferring the same source file.
6. Do not interpolate or carry values beyond these bounds.

The bounds describe the join, not an assertion that board processes share a
timestamp. They are intentionally visible command-line defaults.

## Missing Data

The legacy fixed-width shape has no null syntax. This implementation uses:

- `-1` for a missing integer value
- `-1.000` for missing HDOP or VDOP

In particular, `n_files_queued` is always `-1` until `mermaid-records` exposes
an observed queue count. A missing upload summary is also `-1`, not a fabricated
zero. GPS latitude and longitude cannot be missing because GPS is the row
anchor.

## Output And Provenance

Each instrument is written to `<instrument_id>_all.txt` using the exact legacy
fixed-width column order and spacing. No status or provenance text appears in
that primary file. A sidecar at `audit/<instrument_id>_all.jsonl` records the
GPS anchor, emitted values, joined source files and timestamps, offsets, and
per-group `observed`, `matched`, or `missing` status for every output row.

`scripts/build_location_tables.py` also prints per-instrument counts of LOG
positions, MER-only positions, and rows with complete vitals.

## Legacy Comparison

`~/mermaid/esoloc/` is an untrusted derived product of unknown
provenance. It is compared only after generation and never supplies a product
value or row-selection rule. The comparison walks from each legacy row to the
nearest normalized-derived GPS row and records:

- row-count difference
- nearest normalized-derived timestamp offset
- nearest normalized-derived position distance
- exact vital-tuple agreement on that nearest row
- count and timestamps of legacy rows with no normalized GPS observation within
  one hour

`scripts/compare_eso_locations.py` writes a Markdown report so successive runs
can be retained as an empirical log of how the normalized-record product
differs from the old derived output.

## Pseudocode

```text
for instrument directory:
    log_positions, exact_dops = read log_gps_records
    mer_positions = read mer_environment_records GPSINFO
    positions = log_positions + MER positions not duplicating a LOG fix

    vitals = assemble same-source Vbat + Pint + Pext within 10 seconds
    commands = parse numeric command messages
    uploads = read upload session summaries

    for position in chronological positions:
        vital = nearest complete snapshot within one hour
        command = nearest command within 30 minutes
        uploaded = first following summary within 30 minutes
        write observed values; write -1 for unavailable joined values
```

## Known Ambiguities

- Queue count cannot be mapped from the current normalized schema.
- MER-only GPS positions have no DOP.
- Several GPS observations may legitimately share one vital/status snapshot.
- A temporal match does not prove semantic identity; the bounded rules avoid
  presenting distant events as one snapshot.
- Legacy timestamps and coordinates can differ by minutes and meters because
  that product used a different row anchor and source mix.

## Minimal Implementation

Keep the publisher as a single standard-library script: read normalized JSONL,
assemble snapshots, perform bounded joins, and format rows. Keep discovery and
legacy comparison as separate read-only scripts so validation does not become
production policy.
