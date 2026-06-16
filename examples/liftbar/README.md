# Liftbar example (flying gantry)

A real-world liftbar setup taken from a **Voron 2.4 / StealthChanger** build
with 4 tools, **dual liftbar rails**, and a Cartographer probe on the shuttle.

A *liftbar* is a separate Z-lifter rail (a `[manual_rail]`) that carries the
tool docks up and down. During a tool change the toolhead only moves in X/Y —
the liftbar provides the Z motion to engage and release tools. This is the
**"Liftbar + Flying gantry"** dock layout listed in
[`../README.md`](../README.md).

These files are working configs lightly adapted for sharing. Pins, heights,
speeds, probe coordinates and section names (`tool ebbT0` …) are specific to
this machine — copy what you need and tweak for yours.

## Where each change lives

| File | What it contains |
|------|------------------|
| [`liftbar.cfg`](liftbar.cfg) | Core liftbar macros: `LIFTBAR_HOME`, `LIFTBAR_MOVE` (with panel-aware Z capping), `LIFTBAR_STOW`, `LIFTBAR_LAYER_CHANGE`, `LIFTBAR_PARK_TOP`, the **panel macros** `PANEL_ON` / `PANEL_OFF`, `MOTORS_OFF`, and `TEST_LIFTBAR_SPEED`. |
| [`toolchanger.cfg`](toolchanger.cfg) | The main `[toolchanger]` config: liftbar `params_*`, the `dropoff_gcode` / `pickup_gcode` that move the liftbar concurrently with the gantry (`SYNC=0` … `SYNC=1`), the `DOCK_ALIGN_*` calibration helpers, and the `[homing_override]` that re-orders XYZ homing around the liftbar / `INITIALIZE_TOOLCHANGER`. |
| [`hardware.cfg`](hardware.cfg) | `[manual_rail liftbar]` + `[manual_rail liftbar1]` and their `[tmc2209]` drivers, the `[toolchanger]` `params_liftbar_*` parameters (as a paste-in snippet), and the `[idle_timeout]` that **homes the liftbar before power/motors turn off**. |
| [`homing.cfg`](homing.cfg) | Liftbar-aware homing/leveling: `G32`, `QUAD_GANTRY_LEVEL` (raises the liftbar clear of the gantry before QGL), `CG28`/`CG32`, `_HOME_X` (sensorless), and `_ADJUST_Z_POSITION_WITH_TOOL_OFFSET`. |
| [`toolhead_calibration.cfg`](toolhead_calibration.cfg) | Per-tool offset calibration: `CALIBRATE_TOOL_OFFSETS` (full XY+Z via contact probe) and the Cartographer-touch `CALIBRATE_TOOL_Z_BASELINE` / `CALIBRATE_TOOL_Z_OFFSET` / `CALIBRATE_TOOL_Z_OFFSETS` Z-only flow. |

## The "homing details" specifically

- **Panel macro** — `PANEL_ON` / `PANEL_OFF` in [`liftbar.cfg`](liftbar.cfg).
  When the front enclosure panel is attached, the liftbar would crash into it
  at full travel, so `PANEL_ON` caps every `LIFTBAR_MOVE` at `panel_max_z`
  (defaults to on at boot for safety). `PANEL_OFF` restores full travel.

- **Home the liftbar before power off** — the `[idle_timeout]` block in
  [`hardware.cfg`](hardware.cfg). A `manual_rail` has no brake, so before the
  steppers are disabled the bar is lowered back to its endstop
  (`LIFTBAR_HOME` → Z=25) and only then are motors disabled (`MOTORS_OFF`,
  which also clears the homed flag so the next move re-homes). This prevents
  the raised bar from free-falling when power is cut.

## Toolchange integration

The actual dock pickup/dropoff choreography lives in
[`toolchanger.cfg`](toolchanger.cfg). The key pattern: each tool change
dispatches `LIFTBAR_MOVE … SYNC=0` so the liftbar moves concurrently with the
X/Z gantry approach, then `LIFTBAR_MOVE SYNC=1` waits for the slower of the
two. The toolhead only moves in X/Y; the liftbar provides the Z engage/release
motion. That file also contains the `DOCK_ALIGN_*` helpers for dialing in park
positions and the `[homing_override]` that re-orders XYZ homing around the
liftbar and `INITIALIZE_TOOLCHANGER`.
