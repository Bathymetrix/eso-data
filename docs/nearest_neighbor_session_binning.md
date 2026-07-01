# Bounded Nearest-Neighbor Telemetry Binning

The generated table is not a reconstruction of operational GPS, Iridium, or
`.vit` sessions. It is a time-indexed product in which each observed GPS
position defines a row and independently recorded telemetry is assigned to
nearby GPS rows. A value appearing on a GPS row therefore means “this was the
best eligible row for this observation,” not “the GPS process produced this
value” or “both values belonged to one firmware process.”

This distinction matters because GPS acquisition, battery monitoring,
pressure measurement, and Iridium communication are separate processes. For
example, a line reporting the number of files uploaded does not intrinsically
belong to the GPS fix that preceded it. GPS timestamps provide the bins used
to organize the otherwise independent observations.

## Matching policy

The output rows are anchored by both:

- LOG `fix_position` observations; and
- MER `GPSINFO` observations.

DOP, battery, internal pressure, external pressure, command-count, and
upload-count observations are matched independently. For each telemetry
family:

1. Except for DOP, only observations within the configured symmetric window
   are eligible. The default is 300 seconds before or after the GPS anchor.
2. An observation can be consumed by at most one GPS row. It is not copied
   into adjacent rows.
3. A candidate from the same source file as an anchor is preferred over a
   candidate from another source file. Among otherwise equivalent choices,
   the smaller absolute time offset is preferred.
4. Battery summary observations are preferred over ordinary instantaneous
   voltage observations because a summary can also supply minimum voltage.
5. DOP is matched only to LOG GPS anchors and is directional: the DOP
   observation must occur at or after the anchor and no more than the
   configured DOP window later. An earlier DOP observation is never assigned
   to a later GPS anchor. HDOP and VDOP come from the same DOP observation.
6. Each telemetry family is matched separately. The battery, pressure,
   command count, and upload count on one row need not describe a single
   firmware session.

The audit sidecar records the signed offset:

```text
offset_seconds = telemetry observation time - GPS anchor time
```

A positive offset means that the observation occurred after the anchor; a
negative offset means that it occurred before the anchor.

“Nearest-neighbor session binning” is convenient shorthand, but “session”
refers to the resulting time bin, not to an inferred firmware or Iridium
session.

## P0006 example: 26 June 2018

The relevant output is:

```text
P0006   26-Jun-2018 19:14:05   -14.433683  -179.489850   0.640  1.000    15262    NaN      NaN   NaN  NaN     7 NaN NaN
P0006   26-Jun-2018 19:19:35   -14.434633  -179.485183     NaN    NaN    15150    NaN      NaN   NaN  NaN   NaN NaN NaN
P0006   26-Jun-2018 19:19:46   -14.434667  -179.485050   0.630  0.960    15276    NaN    87302   NaN  NaN   NaN NaN   5
```

The first and third anchors are LOG positions from `06_5B32904C.LOG`. The
middle anchor is a `GPSINFO` observation from `06_5B33E264.MER`.

The LOG records the first position at `19:14:05`, seven commands received at
`19:15:50`, five files uploaded at `19:18:14`, and the second LOG position at
`19:19:46`. The command count is assigned to the first LOG anchor:

```text
19:15:50 - 19:14:05 = +105 seconds
```

The upload count has three nearby anchors:

| Eligible GPS anchor | Source | Signed offset | Absolute offset |
| --- | --- | ---: | ---: |
| `19:14:05` | `06_5B32904C.LOG` | `+249 s` | `249 s` |
| `19:19:35` | `06_5B33E264.MER` | `-81 s` | `81 s` |
| `19:19:46` | `06_5B32904C.LOG` | `-92 s` | `92 s` |

Although the MER anchor is eleven seconds closer than the second LOG anchor,
the upload observation and the second LOG anchor have the same source file.
The same-source preference therefore places `n_files_uploaded = 5` on the
`19:19:46` row. The first LOG row is 249 seconds away and loses on temporal
distance.

This assignment does not claim that the upload was caused by, followed, or
operationally associated with the second GPS acquisition. It says only that
the second LOG GPS anchor is the preferred bin for that independent Iridium
observation under the matching policy.

## P0006 example: 27 June 2018

The relevant output is:

```text
P0006   27-Jun-2018 19:15:22   -14.453333  -179.485017     NaN    NaN    14785    NaN      NaN   NaN  NaN   NaN NaN NaN
P0006   27-Jun-2018 19:15:33   -14.453333  -179.485017   0.620  1.000    14696  14087    84941    79   30   NaN NaN NaN
P0006   27-Jun-2018 19:16:42   -14.453383  -179.485033     NaN    NaN    14602    NaN      NaN   NaN  NaN   NaN NaN NaN
P0006   27-Jun-2018 19:16:53   -14.453400  -179.485033   0.600  0.920    14711    NaN      NaN   NaN  NaN     7 NaN NaN
P0006   27-Jun-2018 19:21:53   -14.453650  -179.485150     NaN    NaN    14763    NaN      NaN   NaN  NaN   NaN NaN NaN
P0006   27-Jun-2018 19:22:04   -14.453667  -179.485150   0.610  0.910    14937    NaN    85292   NaN  NaN   NaN NaN   2
```

This sequence contains three MER/LOG pairs of nearby position observations.
It deliberately retains all six anchors instead of collapsing each pair.

The summary battery, minimum voltage, internal pressure, and external pressure
observations at `19:14:33`–`19:14:35` come from
`06_5B32904C.LOG`. They are assigned to the same-source LOG anchor at
`19:15:33`, with offsets of `-60` to `-58` seconds. The command count at
`19:18:32` comes from `06_5B33E271.LOG` and is assigned to that file's
`19:16:53` anchor, an offset of `+99` seconds.

The two-file upload observation occurs at `19:20:37`. Its principal nearby
anchors are:

| Eligible GPS anchor | Source | Signed offset | Absolute offset |
| --- | --- | ---: | ---: |
| `19:16:53` | `06_5B33E271.LOG` | `+224 s` | `224 s` |
| `19:21:53` | `06_5B3534DC.MER` | `-76 s` | `76 s` |
| `19:22:04` | `06_5B33E271.LOG` | `-87 s` | `87 s` |

The upload is placed on the `19:22:04` row. As on 26 June, the slightly closer
MER anchor does not override the same-source LOG preference.

## Relationship to the historical `.vit` summaries

The historical `.vit` material is not an input to this repository's table
builder. It is nevertheless useful for understanding the observations. A
`.vit` block presents a curated operational summary: one position, DOP,
battery summary, pressure values, command count, queue count, upload count,
and termination marker are collected into a single human-readable session.

The new table expands that view in two ways:

- it preserves additional LOG and MER position observations rather than
  reducing them to one position per `.vit` block; and
- it preserves the independent timing and provenance of each telemetry
  family rather than forcing every value from a `.vit` block onto one GPS
  row.

For the 26 June `.vit` block, the position, DOP, and seven-command observation
correspond to the `19:14:05` table row, while the five-file upload observation
is binned to the `19:19:46` row. The intervening MER position at `19:19:35`
and the second LOG position at `19:19:46` make explicit observations that the
single `.vit` summary does not present as separate rows.

The 27 June `.vit` block is even more clearly distributed:

- `Vbat 14696mV (min 14087mV)`, `Pint 84941Pa`, and
  `Pext 79mbar (range 30mbar)` appear on the `19:15:33` row;
- position `S14deg27.204mn, W179deg29.102mn`, DOP `0.600/0.920`,
  and seven commands appear on the `19:16:53` row; and
- two uploaded files appear on the `19:22:04` row.

Thus a `.vit` “session” may map to several table rows. This is intentional:
the table is a higher-cadence, provenance-preserving view, not a row-for-row
replacement for the `.vit` presentation.

The `.vit` queue counts (`5 file(s) to upload` and `2 file(s) to upload`) do
not currently have a normalized source field. Consequently
`n_files_queued` remains `NaN` in every generated row. Differences between
the displayed `.vit` timestamps and normalized LOG/MER timestamps should also
not be interpreted as join offsets: `.vit` is not consulted by the matching
algorithm.
