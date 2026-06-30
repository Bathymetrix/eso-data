### Public Float Table Design

## Authority And Scope

The product is derived only from normalized JSONL. The raw source files under
~/mermaid/server_everyone/ are the source of truth for input data used to build
that normalized JSONL. Any normalized output directory, including the current
default ~/mermaid/records/, is a generated artifact from a particular
mermaid-records run; because that output is currently in flux, it should not be
treated as a stable baseline comparator against ~/mermaid/esoloc/. The
generated tables in ~/mermaid/esoloc/ are useful comparison material, but they
do not decide row cadence or values.

The normalized families are asynchronous event streams. GPS, DOP, battery,
pressure, command, and upload observations have different timestamps and row
counts. Joins must be temporal and provenance-aware, never by line number or
equal timestamp.

The implementation does not read raw LOG or VIT files and never modifies either
input directory.

## Join Philosophy

The normalized record families represent independent telemetry streams emitted
at different times. This product intentionally preserves those streams rather
than manufacturing synchronized snapshots.

GPS observations define output rows. Other telemetry streams are joined using
bounded nearest-neighbor matching. Each non-GPS observation may contribute to
at most one output row, preserving the original cadence of every telemetry
stream and preventing stale values from being propagated across multiple
locations.

## Relevant Normalized Families

Common provenance fields are instrument_id, instrument_serial,
source_file, source_container, and either record_time/log_epoch_time or
gpsinfo_date.

Family	Relevant fields
log_gps_records	gps_record_kind, raw_values.latitude, raw_values.longitude, raw_values.hdop, raw_values.vdop
mer_environment_records	environment_kind == "gpsinfo", gpsinfo_date, raw_values.lat, raw_values.lon
log_battery_records	battery_record_kind, voltage_mv, minimum_voltage_mv
log_pressure_temperature_records	internal_pressure_pa, external_pressure_mbar, external_pressure_range_mbar
log_iridium_records	nested iridium_events, especially command_summary and upload_session_summary

## Column Mapping

Output column	Normalized source and rule
station	GPS record instrument_id
datetime	GPS observation time in UTC, formatted %d-%b-%Y %H:%M:%S
lat, lon	LOG fix_position plus MER GPSINFO observations
hdop, vdop	nearest unused LOG dop observation within the configured DOP window, preferring the same source file
battery_mv, min_voltage_mv	nearest unused battery observation, preferring battery_record_kind == "vbat_summary"
internal_pressure_pa	nearest unused explicit internal-pressure observation
external_pressure_mbar, pressure_range_mbar	nearest unused explicit Pext observation
n_commands_received	nearest unused Iridium command_summary event
n_files_queued	not present in current normalized outputs; emitted as `NaN`
n_files_uploaded	nearest unused Iridium upload_session_summary event

## Row Anchor Policy

Emit one row per normalized GPS observation:

1. Include every LOG `fix_position` observation.
2. Include every MER `GPSINFO` observation.
3. Treat every MER and LOG GPS emission as unique and true. Do not merge,
   suppress, or deduplicate MER observations against nearby LOG observations,
   even when time and position are similar.

No GPS row is removed merely because battery, pressure, command, or upload data
is sparse.

## Matching Policy

1. Pair LOG positions and DOP observations using the nearest matching DOP from
    (most-commonly) the same source file.
2. Match battery observations from log_battery_records within the configured
    vital window.
3. Match pressure observations from
    log_pressure_temperature_records within the configured vital window.
4. Match Iridium command-summary events within the configured status window.
5. Match Iridium upload-session-summary events within the configured status
    window.
6. Each matched observation is consumed at most once. Once assigned to a GPS
    anchor it is unavailable for later joins.
7. Do not interpolate or carry observations beyond the configured windows.

The bounds describe the join, not an assertion that board processes share a
timestamp. They are intentionally visible command-line defaults.

## Missing Data

The legacy fixed-width table has no explicit null syntax. This implementation
uses the literal string `NaN` for every unavailable value, regardless of
whether the column is otherwise formatted as an integer or floating-point
quantity.

In particular:

- `n_files_queued` is always `NaN` until `mermaid-records` exposes an observed
  queue count.
- Missing upload summaries are written as `NaN`.
- Missing DOP values are written as `NaN`.
- Missing battery or pressure observations are written as `NaN`.

Unused observations are preferred over reusing an older observation for a later
GPS fix.

GPS latitude and longitude cannot be missing because GPS observations define
the output rows.

## Output And Provenance

Each instrument is written to <instrument_id>_all.txt using the exact legacy
fixed-width column order and spacing. No status or provenance text appears in
that primary file.

A sidecar at audit/<instrument_id>_all.jsonl records the GPS anchor, emitted
values, joined source files and timestamps, join offsets, and per-field match
status. Every public value can therefore be traced back to exactly one
normalized observation.

scripts/build_esoloc.py may also report summary statistics such as
GPS rows processed and successfully matched observations.

## Legacy Comparison

~/mermaid/esoloc/ is an untrusted derived product of unknown
provenance. It is compared only after generation and never supplies a product
value or row-selection rule.

The comparison walks from each legacy row to the nearest normalized-derived GPS
row and records:

* row-count difference
* nearest normalized-derived timestamp offset
* nearest normalized-derived position distance
* exact agreement of matched status values
* count and timestamps of legacy rows with no normalized GPS observation within
    the configured comparison window (300 seconds by default)

scripts/compare_esoloc.py writes a Markdown report so successive runs
can be retained as an empirical log of how the normalized-record product
differs from the historical derived output.

## Pseudocode

for each instrument:
    read LOG GPS observations
    read MER GPSINFO observations
    read DOP observations
    read battery observations
    read pressure observations
    read Iridium command summaries
    read Iridium upload summaries
    for each GPS anchor in chronological order:
        attach nearest unused DOP
        attach nearest unused battery observation
        attach nearest unused pressure observation
        attach nearest unused command summary
        attach nearest unused upload summary
        write output row

## Known Ambiguities

* Queue count cannot be mapped from the current normalized schema and is
  therefore emitted as `NaN`.
* MER-only GPS observations have no DOP.
* Multiple GPS observations may lie within the join window of a single status
    observation. Each status observation is assigned only to its nearest GPS
    anchor and is never duplicated across rows.
* A temporal match does not prove semantic identity; the bounded rules avoid
    presenting distant events as one observation.
* Legacy timestamps and coordinates can differ by minutes and meters because
    that product used a different row anchor and source mix.

## Minimal Implementation

Keep the publisher as a single standard-library script: read normalized JSONL,
perform bounded one-to-one joins, and format rows. Keep legacy comparison as a
separate read-only script so validation does not become production policy.
