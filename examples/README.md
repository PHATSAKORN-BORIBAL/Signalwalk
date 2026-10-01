# Examples

| File | What it is |
|---|---|
| `floorplans/apartment.json` | 12 x 8 m two-bedroom apartment, router in a corner, 8 allowed router positions (outlets) |
| `floorplans/office.json` | 16 x 8 m office with a heavy lift core and glass meeting rooms; router positions are searched on a grid |
| `surveys/apartment_demo.csv` | 20 **simulated** measurements (seed 3) |
| `surveys/office_demo.csv` | 22 **simulated** measurements (seed 3) |

```bash
python -m signalwalk analyze examples/surveys/apartment_demo.csv --floorplan apartment
python -m signalwalk analyze examples/surveys/office_demo.csv --floorplan office --svg office.svg
python -m signalwalk validate-floorplan examples/floorplans/office.json
```

## Floor plan format

```json
{
  "name": "My flat",
  "width_m": 12.0, "height_m": 8.0,
  "router": {"x": 1.0, "y": 1.0},
  "router_candidates": [{"x": 3.2, "y": 0.6}],          // optional: where a router could actually go
  "walls": [{"x1": 0, "y1": 0, "x2": 12, "y2": 0, "kind": "heavy"}],   // kind: light | interior | heavy
  "rooms": [{"name": "Living room", "x": 0, "y": 0, "w": 6.5, "h": 4.5, "priority": 1.0}]
}
```

(The comments are for illustration; real JSON has none.) Coordinates are metres from the **top-left** corner,
x to the right, y downwards. Leave a gap in a wall for a doorway. `priority` says how much a room matters when
scoring coverage (a home office 1.5, a bathroom 0.6).

## Survey CSV format

Header `x_m,y_m,rssi_dbm` (optional: `n_readings,spread_db,source`). One row per measured spot.
