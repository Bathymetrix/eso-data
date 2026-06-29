mermaid-records Column Mapping

VIT2TBL column	Current normalized source	Keys / selector	Notes
Station, e.g. P0023	any LOG family row	instrument_id	Use the anchor GPS row’s instrument_id.
Datetime	log_gps_records.<serial>.jsonl or mer_environment_records.<serial>.jsonl	record_time where gps_record_kind == "fix_position", or gpsinfo_date where environment_kind == "gpsinfo"	Convert ISO UTC to 08-Oct-2018 10:07:48 format only in the table writer.
Latitude decimal degrees	log_gps_records or mer_environment_records	raw_values.latitude where gps_record_kind == "fix_position", plus GPSINFO raw_values.lat	Convert the source-literal coordinate (e.g. S14deg41.862mn) or MER ddmm-style coordinate to decimal degrees in eso-data.
Longitude decimal degrees	log_gps_records or mer_environment_records	raw_values.longitude where gps_record_kind == "fix_position", plus GPSINFO raw_values.lon	Same conversion policy as latitude.
HDOP	log_gps_records	nearest unused gps_record_kind == "dop" record from the same source file within the configured DOP window; raw_values.hdop	DOP observations are consumed at most once and assigned to the nearest GPS anchor.
VDOP	log_gps_records	same matched DOP record; raw_values.vdop	Paired with HDOP from the same observation.
Battery level (mV)	log_battery_records.<serial>.jsonl	nearest unused voltage_mv within the configured vital window	Prefer battery_record_kind == "vbat_summary" when available because it also provides minimum voltage.
Minimum voltage (mV)	log_battery_records	same matched vbat_summary.minimum_voltage_mv	Emitted only from the same matched battery observation.
Internal pressure (Pa)	log_pressure_temperature_records.<serial>.jsonl	nearest unused internal_pressure_pa within the configured vital window	Uses only explicit internal-pressure observations.
External pressure (mbar)	log_pressure_temperature_records	nearest unused external_pressure_mbar within the configured vital window	Uses only explicit Pext observations; generic pressure samples are not substituted.
Pressure range (mbar)	log_pressure_temperature_records	same matched external_pressure_range_mbar	Emitted only with the matched Pext observation.
Commands received	log_iridium_records.<serial>.jsonl	nearest unused nested event where iridium_event_kind == "command_summary"; received_command_count	Uses the parsed Iridium session event rather than raw message text.
Files queued for upload	unavailable in current normalized records	no normalized field	Written as missing (`NaN`) until queue-count telemetry is exposed by mermaid-records.
Files uploaded	log_iridium_records.<serial>.jsonl	nearest unused nested event where iridium_event_kind == "upload_session_summary"; uploaded_file_count	Uses the parsed Iridium upload-session summary event.

Join Policy

LOG fix_position and MER GPSINFO observations define the output rows.

DOP, battery, pressure, and Iridium status observations are joined independently
using bounded nearest-neighbor matching. Preference is given to observations
from the same source LOG file when possible.

Each non-GPS observation may be consumed by at most one output row. Once a
DOP, battery, pressure, command-summary, or upload-summary observation has been
assigned to its nearest GPS anchor, it is not reused for neighboring GPS rows.
The product intentionally preserves the cadence of the underlying telemetry
streams rather than propagating stale status values across multiple locations.
