# Hole Pattern Generator

Convert grayscale images into precise hole and countersink patterns for laser, CNC, or drilling templates.  
Exports to **DXF**, **PDF**, **SVG**, **CSV**, and **STEP (FreeCAD)**.  
Built entirely in **Python + Tkinter**, no external dependencies beyond standard scientific libs.

---

## Features
- Convert any grayscale image to a perforated plate pattern  
- Tone mapping to drill diameters (custom drill sets supported)  
- Adjustable grid, margins, pitch, and countersink geometry  
- Color-customizable preview (front/core/background)  
- Supports tiling of large panels  
- Connectors for tiling: **dowel**, **dovetail**, or **hanger pocket**  
- Exports:
  - **DXF R12** (2D circles with separate layers for holes & countersinks)
  - **PDF / SVG** (visual preview)
  - **CSV** (hole list with coordinates and diameters)
  - **STEP** (3D export via FreeCAD)

---

## Known Limitations / Work in Progress

- FreeCAD STEP export:
  - Requires local FreeCAD installation and proper `sys.path` setup  
  - No error handling if FreeCAD modules are missing  
- GUI usability:
  - Some mouse actions (brush/pan) are clunky  
  - No keyboard shortcuts for quick input yet  
- Preview rendering:
  - Large images can be slow  
  - Zoom and pan reset after parameter changes  
- Batch export:
  - Works, but no progress bar or error summary  
- Tiling / connectors:
  - Only supported for STEP, not mirrored in 2D exports  
- No standalone EXE yet (needs Python runtime)

---

##  Planned / Future Additions

- [ ] Add progress indicator for batch and export operations  
- [ ] Improve brush tool with undo/redo and keyboard shortcuts  
- [ ] Implement DXF layer color coding  
- [ ] Add option for drilling depth / z-mapping  
- [ ] CLI mode (no GUI, headless batch converter)  
- [ ] Optional SVG import for pattern masks  
- [ ] Save/load full project state (`.json`)  
- [ ] Auto-update checker  
- [ ] Build Windows standalone app via PyInstaller

---

## Requirements

Python ≥ 3.9  
Install dependencies:

```bash
pip install pillow numpy reportlab

