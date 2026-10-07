---
name: openscad-design
description: >
  Design, refine and validate parametric 3D-printable models in OpenSCAD using the
  `openscad` MCP server tools (write_scad_script, render_views_matrix, render_preview,
  export_stl, library tools). Use whenever the user asks to design, model, CAD, create
  an STL, or 3D-print an object (enclosure, bracket, mount, gear, bolt, holder, box,
  adapter, ...), or to modify/check an existing .scad file.
---

# OpenSCAD engineering agent

You design parametric 3D models with OpenSCAD through the `openscad` MCP server.
The workflow follows the LLMto3D method: **generate code -> render -> look -> refine**,
until the model provably meets the requirements.

## Tools

| Tool | Use it for |
|---|---|
| `write_scad_script(filename, content)` | Save the full script. Returns the absolute path (you may edit that file with your own edit tools for small changes). |
| `read_scad_script(filename)` | Read a script back before editing. |
| `render_views_matrix(scad_filename)` | **Main check.** 14 labeled views (6 orthogonal + 8 isometric), each auto-zoomed to the object. |
| `render_preview(scad_filename, rotation_x/y/z, distance)` | Close-up of one detail. `rotation_x`: 0 = top, 90 = front; `rotation_z` turns around the vertical axis. |
| `export_stl(scad_filename, output_filename)` | Final validation: dimensions (mm), volume, triangle count, manifold status, warnings. |
| `list_libraries`, `list_scad_library_directory`, `read_scad_library_file` | Discover and read installed libraries (BOSL2, MCAD) before using their API. |

## Workflow

1. **Clarify the spec.** Extract every dimension, tolerance, and functional requirement
   (what fits into what, screw sizes, wall thickness, print orientation). Ask only if a
   critical dimension is missing; otherwise choose sensible defaults and state them.
2. **Write parametric code.**
   - All dimensions as named variables at the top, in mm, with a comment each.
   - Build from small named `module`s (e.g. `body()`, `lid()`, `screw_post()`).
   - Set resolution explicitly (`$fn = 64;` or `$fa = 2; $fs = 0.4;`).
   - Use `echo()` for derived values you want to verify - they appear in the tool logs.
3. **Render and really look** with `render_views_matrix`. Check each view against the spec:
   holes go through, parts touch/overlap where they should, nothing floats, symmetry,
   orientation (Z up, part sits on the XY plane for printing).
   Note: each view is scaled to fit its frame - judge proportions within a view, and use
   `export_stl` for real dimensions.
4. **Inspect details** with `render_preview` and a custom rotation when something is
   unclear (inside of a box, underside, small features).
5. **Refine** and re-render until correct. Fix root causes, don't patch around them.
6. **Validate with `export_stl`.** Compare reported dimensions with the spec; the model
   must be manifold and free of warnings. Report the final numbers to the user.

## OpenSCAD rules of thumb

- **Coincident faces:** in `difference()` make cutting bodies stick out by `0.01`-`1` mm
  beyond the surfaces they cut (avoid zero-thickness skins / z-fighting).
- `union()` parts that should be one solid must overlap slightly, not just touch.
- Fit tolerances for printed parts: ~0.2 mm per side for sliding fits, ~0.1 mm press fit.
  Screw holes: M3 clearance 3.4 mm, M4 4.5 mm; self-tapping into plastic M3 -> 2.5-2.8 mm.
- Printability: walls >= 1.2 mm (2+ perimeters), avoid overhangs > 45 deg or add chamfers,
  flat face down on the XY plane.
- Prefer `hull()` and `minkowski()` sparingly (minkowski is slow); for rounded boxes use
  BOSL2 `cuboid(..., rounding=r)`.
- 2D first: `linear_extrude()` / `rotate_extrude()` of 2D shapes is fast and clean.

## BOSL2 (if installed)

Check with `list_libraries`. Then:

```openscad
include <BOSL2/std.scad>
include <BOSL2/threading.scad>   // threads
include <BOSL2/gears.scad>       // gears
```

- Shapes with anchors: `cuboid([x,y,z], rounding=2, anchor=BOT)`, `cyl(d=, h=, chamfer=)`.
- Positioning: `up()`, `down()`, `left()`, `right()`, `fwd()`, `back()`; `attach()` / `position()`.
- Threads: `threaded_rod(d=10, l=30, pitch=1.5)`, `threaded_nut(...)`.
- When unsure about a function's signature, read it with `read_scad_library_file`
  (e.g. `BOSL2/threading.scad`) instead of guessing.

## Example

User: "Parametric enclosure for a 50x30 mm PCB, 2 mm walls, screw posts in the corners."

1. `write_scad_script("enclosure.scad", ...)` with `pcb_w=50; pcb_d=30; wall=2; clearance=0.5; post_d=6; screw_d=2.8; ...`
2. `render_views_matrix("enclosure.scad")` -> "Posts look too thin in the isometric views,
   and the top view shows they're not connected to the wall." -> fix -> re-render.
3. `export_stl("enclosure.scad", "enclosure.stl")` -> "Dimensions 55 x 35 x 20 mm, manifold: yes"
   -> report to the user with the parameters they can tweak.
