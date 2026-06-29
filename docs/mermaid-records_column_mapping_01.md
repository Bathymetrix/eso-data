| VIT2TBL column | Current normalized source | Keys / selector | Notes |
| --- | --- | --- | --- |
| Station, e.g. `P0023` | any LOG family row | `instrument_id` | Use anchor GPS row’s `instrument_id`. |
| Datetime | `log_gps_records.<serial>.jsonl` | `record_time` where `gps_record_kind == "fix_position"` | Convert ISO UTC to `08-Oct-2018 10:07:48` style only in the table writer. |
| Latitude decimal degrees | `log_gps_records` | `raw_values.latitude` where `gps_record_kind == "fix_position"` | Currently source-literal, e.g. `S14deg41.862mn`; decimal conversion belongs in `vit2tbl`, not normalization. |
| Longitude decimal degrees | `log_gps_records` | `raw_values.longitude` where `gps_record_kind == "fix_position"` | Same conversion note. |
| HDOP | `log_gps_records` | exact same-source/time `gps_record_kind == "dop"`, `raw_values.hdop` | Unknown for MER-only GPS rows. |
| VDOP | `log_gps_records` | exact same-source/time `gps_record_kind == "dop"`, `raw_values.vdop` | Unknown for MER-only GPS rows. |
| Battery level mV | `log_operational_records.message` | nearest complete same-source `Vbat ...mV (min ...mV)` snapshot within the configured vital window | Parsed from the board's legacy-style status line. |
| Minimum voltage mV | `log_operational_records.message` | same matched `Vbat ... (min ...mV)` snapshot | Kept with battery level as one coherent vital snapshot. |
| Internal pressure Pa | `log_operational_records.message` | same matched snapshot, `Pint ...Pa` or `internal pressure ...Pa` | Joined with Vbat/Pext as a complete snapshot. |
| External pressure mbar | `log_operational_records.message` | same matched snapshot, `Pext ...mbar (rng ...mbar)` | Do not use generic pressure samples here. |
| Pressure range mbar | `log_operational_records.message` | same matched `Pext ... (rng ...mbar)` snapshot | Kept with external pressure as one coherent vital snapshot. |
| Commands received | `log_operational_records.message` | nearest numeric `N cmd(s) received` event within the configured status window | Prefer same source file when possible. |
| Files queued for upload | unavailable in current normalized records | no direct normalized key | Written as missing (`-1`) until an observed queue count is exposed. |
| Files uploaded | `log_transmission_records.<serial>.jsonl` | nearest following `upload_session_summary.uploaded_file_count` within the configured status window | From `N file(s) uploaded`. |
