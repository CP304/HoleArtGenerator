import os, json, math, tkinter as tk
from tkinter import filedialog, messagebox, colorchooser, simpledialog
from dataclasses import dataclass, asdict
from typing import List, Tuple
import numpy as np
from PIL import Image, ImageTk

# -------------------------- Parameter --------------------------
@dataclass
class Params:
    width_mm: float = 594.0
    height_mm: float = 841.0
    keep_aspect: bool = True

    margin_mm: float = 15.0
    pitch_x_mm: float = 15.0
    pitch_y_mm: float = 15.0

    gamma: float = 1.0
    invert: bool = False
    clamp_edges: bool = True

    use_drillset: bool = True
    drillset_str: str = "3, 3.5, 4, 4.5, 5, 6, 8, 10, 12"

    stagger: bool = False
    stagger_ratio: float = 0.5

    csk_enable: bool = True
    csk_factor: float = 1.6
    min_web_mm: float = 2.0

    plate_thickness_mm: float = 2.0
    csk_angle_deg: float = 90.0

    col_front: tuple = (245,245,245)
    col_core:  tuple = (200, 40, 40)
    col_bg:    tuple = (20, 20, 20)

    preview_scale: float = 0.35
    svg_if_no_pdf: bool = True

@dataclass
class StepTileOptions:
    enable: bool = False
    tile_w_mm: float = 300.0
    tile_h_mm: float = 300.0
    joint_type: str = "none"     # "none" | "dowel" | "dovetail"

    # Dowel
    dowel_diam_mm: float = 8.0
    dowel_depth_mm: float = 12.0
    dowel_spacing_mm: float = 120.0
    dowel_edge_offset_mm: float = 40.0

    # Dovetail
    dt_width_mm: float = 20.0
    dt_depth_mm: float = 6.0
    dt_opening_mm: float = 12.0
    dt_pitch_mm: float = 120.0
    dt_edge_offset_mm: float = 40.0

    # Hanger Pocket
    hanger_enable: bool = False
    hanger_w_mm: float = 30.0
    hanger_h_mm: float = 10.0
    hanger_depth_mm: float = 4.0
    hanger_offset_x_mm: float = 0.0
    hanger_offset_y_mm: float = 30.0

    # Edge Finish
    edge_finish: str = "none"  # "none" | "chamfer" | "fillet"
    edge_size_mm: float = 1.0

# -------------------------- Tooltips --------------------------
class Tooltip:
    def __init__(self, widget, text: str, delay_ms=400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.tipwindow = None
        self.id = None
        widget.bind("<Enter>", self._enter)
        widget.bind("<Leave>", self._leave)
        widget.bind("<ButtonPress>", self._leave)
    def _enter(self, _evt=None): self._schedule()
    def _leave(self, _evt=None): self._unschedule(); self._hidetip()
    def _schedule(self):
        self._unschedule()
        self.id = self.widget.after(self.delay_ms, self._showtip)
    def _unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id); self.id = None
    def _showtip(self):
        if self.tipwindow or not self.text: return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tipwindow = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify="left",
                         background="#ffffe0", relief="solid", borderwidth=1,
                         font=("TkDefaultFont", 9))
        label.pack(ipadx=6, ipady=4)
    def _hidetip(self):
        if self.tipwindow:
            self.tipwindow.destroy(); self.tipwindow = None
def add_tip(widget, text: str): Tooltip(widget, text)

# -------------------------- CoreLogic --------------------------
def load_grayscale(path): return Image.open(path).convert("L")
def fit_image_to_grid(imgL, nx, ny):
    return imgL.resize((nx, ny), Image.Resampling.BOX if hasattr(Image,"Resampling") else Image.BOX)

def build_grid(p: Params):
    W,H = p.width_mm, p.height_mm
    W_eff = W - 2*p.margin_mm
    H_eff = H - 2*p.margin_mm
    nx = int(math.floor(W_eff / p.pitch_x_mm))
    ny = int(math.floor(H_eff / p.pitch_y_mm))
    return nx, ny, W, H

def parse_drillset(s: str):
    vals=[]
    for tok in s.replace(";", ",").split(","):
        tok = tok.strip().replace(",", ".")
        if not tok: continue
        try:
            v = float(tok)
            if v > 0: vals.append(round(v,1))
        except: pass
    vals = sorted(set(vals))
    return vals

def gray_to_range(g, dmin, dmax, gamma=1.0, invert=False, clamp=True):
    x = g/255.0
    if invert: x = 1.0 - x
    x = pow(x, max(1e-6, gamma))
    d = dmin + x*(dmax - dmin)
    if clamp:
        d = max(dmin, min(dmax, d))
    return d

def snap_to_drillset(d: float, drillset):
    if not drillset: return d
    return float(min(drillset, key=lambda v: abs(v - d)))

def limit_csk_diameter(cx_d, p: Params):
    max_dx = p.pitch_x_mm - p.min_web_mm
    max_dy = p.pitch_y_mm - p.min_web_mm
    return max(0.0, min(cx_d, max_dx, max_dy))

def generate_maps(img_path, p: Params):
    imgL = load_grayscale(img_path)
    nx, ny, W, H = build_grid(p)
    if nx<2 or ny<2: raise ValueError("Grid to coarse for selected Parameters.")
    small = fit_image_to_grid(imgL, nx, ny)
    arr = np.array(small, dtype=np.uint8)

    drillset = parse_drillset(p.drillset_str) if p.use_drillset else []
    if p.use_drillset and len(drillset)>=2:
        dmin, dmax = drillset[0], drillset[-1]
    else:
        dmin, dmax = 3.0, 12.0

    d_map   = np.zeros((ny,nx), dtype=np.float32)
    csk_map = np.zeros((ny,nx), dtype=np.float32)

    for y in range(ny):
        for x in range(nx):
            raw = gray_to_range(arr[y,x], dmin, dmax, gamma=p.gamma, invert=p.invert, clamp=p.clamp_edges)
            d = snap_to_drillset(raw, drillset) if p.use_drillset else raw
            d_map[y,x] = d
            csk_map[y,x] = limit_csk_diameter(d * max(1.0, p.csk_factor), p) if p.csk_enable else d
    return d_map, csk_map

# -------------------------- Exports (CSV, DXF, PDF/SVG) --------------------------
def export_csv(eff_d_map, p: Params, out_csv):
    nx, ny, W, H = build_grid(p)
    drillset = parse_drillset(p.drillset_str) if p.use_drillset else []
    with open(out_csv, "w", encoding="utf-8") as f:
        f.write("x_mm,y_mm,diam_mm,bit_mm\n")
        for y in range(ny):
            for x in range(nx):
                cx, cy = cell_center_mm(x, y, p, W)
                d  = round(float(eff_d_map[y, x]), 1)
                bit = d if drillset else ""
                f.write(f"{cx:.1f},{cy:.1f},{d:.1f},{bit}\n")

def export_csv_tiled(eff_d_map, p: Params, opts: StepTileOptions, base_path_no_ext: str):
    nx, ny, W, H = build_grid(p)
    tiles_x = max(1, int(math.ceil(W/max(1e-6, opts.tile_w_mm))))
    tiles_y = max(1, int(math.ceil(H/max(1e-6, opts.tile_h_mm))))
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            ox = tx*opts.tile_w_mm
            oy = ty*opts.tile_h_mm
            w_tile = min(opts.tile_w_mm, W-ox)
            h_tile = min(opts.tile_h_mm, H-oy)
            out_csv = f"{base_path_no_ext}_tile_{tx}_{ty}.csv"
            with open(out_csv, "w", encoding="utf-8") as f:
                f.write("x_mm,y_mm,diam_mm\n")
                for y in range(ny):
                    for x in range(nx):
                        cx, cy = cell_center_mm(x, y, p, W)
                        if ox <= cx <= ox+w_tile and oy <= cy <= oy+h_tile:
                            d = round(float(eff_d_map[y, x]), 1)
                            f.write(f"{cx-ox:.1f},{cy-oy:.1f},{d:.1f}\n")

def export_dxf_r12(eff_d_map, eff_csk_map, p: Params, out_dxf):
    nx, ny, W, H = build_grid(p)
    with open(out_dxf, "w", encoding="ascii") as f:
        f.write("0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nSECTION\n2\nTABLES\n0\nENDSEC\n")
        f.write("0\nSECTION\n2\nENTITIES\n")
        for y in range(ny):
            for x in range(nx):
                cx, cy = cell_center_mm(x, y, p, W)
                r_hole = float(eff_d_map[y,x])*0.5
                r_csk  = float(eff_csk_map[y,x])*0.5
                f.write("0\nCIRCLE\n8\nKEGELSENK\n")
                f.write(f"10\n{cx:.6f}\n20\n{(H-cy):.6f}\n30\n0.0\n40\n{r_csk:.6f}\n")
                f.write("0\nCIRCLE\n8\nLOCH\n")
                f.write(f"10\n{cx:.6f}\n20\n{(H-cy):.6f}\n30\n0.0\n40\n{r_hole:.6f}\n")
        f.write("0\nENDSEC\n0\nEOF\n")

def export_pdf_or_svg(eff_d_map, eff_csk_map, p: Params, out_path_pdf, fallback_svg=True):
    nx, ny, W, H = build_grid(p)
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.units import mm as RLMM
        c = canvas.Canvas(out_path_pdf, pagesize=(W*RLMM, H*RLMM))
        r,g,b = [v/255 for v in p.col_front]
        c.setFillColorRGB(r,g,b); c.rect(0,0,W*RLMM,H*RLMM, fill=1, stroke=0)
        for y in range(ny):
            for x in range(nx):
                cx, cy = cell_center_mm(x, y, p, W)
                Rcs = (float(eff_csk_map[y,x])*0.5)*RLMM
                Rh  = (float(eff_d_map[y,x])*0.5)*RLMM
                r,g,b = [v/255 for v in p.col_core]; c.setFillColorRGB(r,g,b)
                c.circle(cx*RLMM, (H-cy)*RLMM, Rcs, stroke=0, fill=1)
                r,g,b = [v/255 for v in p.col_bg]; c.setFillColorRGB(r,g,b)
                c.circle(cx*RLMM, (H-cy)*RLMM, Rh, stroke=0, fill=1)
        c.showPage(); c.save()
        return True, out_path_pdf
    except Exception:
        if not fallback_svg: raise
        def rgb(col): return f"rgb({col[0]},{col[1]},{col[2]})"
        lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">']
        lines.append(f'<rect x="0" y="0" width="100%" height="100%" fill="{rgb(p.col_front)}"/>')
        for y in range(ny):
            for x in range(nx):
                cx, cy = cell_center_mm(x, y, p, W)
                rc = float(eff_csk_map[y,x])*0.5
                rh = float(eff_d_map[y,x])*0.5
                lines.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{rc:.3f}" fill="{rgb(p.col_core)}"/>')
                lines.append(f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{rh:.3f}" fill="{rgb(p.col_bg)}"/>')
        lines.append("</svg>")
        svg_path = os.path.splitext(out_path_pdf)[0] + ".svg"
        with open(svg_path,"w",encoding="utf-8") as f: f.write("\n".join(lines))
        return False, svg_path

def export_pdf_tiled(eff_d_map, eff_csk_map, p: Params, opts: StepTileOptions, base_path_no_ext: str):
    nx, ny, W, H = build_grid(p)
    tiles_x = max(1, int(math.ceil(W/max(1e-6, opts.tile_w_mm))))
    tiles_y = max(1, int(math.ceil(H/max(1e-6, opts.tile_h_mm))))
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import mm as RLMM
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            ox = tx*opts.tile_w_mm
            oy = ty*opts.tile_h_mm
            w_tile = min(opts.tile_w_mm, W-ox)
            h_tile = min(opts.tile_h_mm, H-oy)
            out = f"{base_path_no_ext}_tile_{tx}_{ty}.pdf"
            c = canvas.Canvas(out, pagesize=(w_tile*RLMM, h_tile*RLMM))
            r,g,b = [v/255 for v in p.col_front]; c.setFillColorRGB(r,g,b)
            c.rect(0,0,w_tile*RLMM,h_tile*RLMM, fill=1, stroke=0)
            for y in range(ny):
                for x in range(nx):
                    cx, cy = cell_center_mm(x, y, p, W)
                    if not (ox <= cx <= ox+w_tile and oy <= cy <= oy+h_tile): continue
                    Rcs = (float(eff_csk_map[y,x])*0.5)*RLMM
                    Rh  = (float(eff_d_map[y,x])*0.5)*RLMM
                    r,g,b = [v/255 for v in p.col_core]; c.setFillColorRGB(r,g,b)
                    c.circle((cx-ox)*RLMM, (h_tile-(cy-oy))*RLMM, Rcs, stroke=0, fill=1)
                    r,g,b = [v/255 for v in p.col_bg]; c.setFillColorRGB(r,g,b)
                    c.circle((cx-ox)*RLMM, (h_tile-(cy-oy))*RLMM, Rh, stroke=0, fill=1)
            c.showPage(); c.save()

def export_svg_tiled(eff_d_map, eff_csk_map, p: Params, opts: StepTileOptions, base_path_no_ext: str):
    nx, ny, W, H = build_grid(p)
    tiles_x = max(1, int(math.ceil(W/max(1e-6, opts.tile_w_mm))))
    tiles_y = max(1, int(math.ceil(H/max(1e-6, opts.tile_h_mm))))
    def rgb(col): return f"rgb({col[0]},{col[1]},{col[2]})"
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            ox = tx*opts.tile_w_mm
            oy = ty*opts.tile_h_mm
            w_tile = min(opts.tile_w_mm, W-ox)
            h_tile = min(opts.tile_h_mm, H-oy)
            out = f"{base_path_no_ext}_tile_{tx}_{ty}.svg"
            lines=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_tile}mm" height="{h_tile}mm" viewBox="0 0 {w_tile} {h_tile}">']
            lines.append(f'<rect x="0" y="0" width="100%" height="100%" fill="{rgb(p.col_front)}"/>')
            for y in range(ny):
                for x in range(nx):
                    cx, cy = cell_center_mm(x, y, p, W)
                    if not (ox <= cx <= ox+w_tile and oy <= cy <= oy+h_tile): continue
                    rc = float(eff_csk_map[y,x])*0.5
                    rh = float(eff_d_map[y,x])*0.5
                    lines.append(f'<circle cx="{cx-ox:.3f}" cy="{cy-oy:.3f}" r="{rc:.3f}" fill="{rgb(p.col_core)}"/>')
                    lines.append(f'<circle cx="{cx-ox:.3f}" cy="{cy-oy:.3f}" r="{rh:.3f}" fill="{rgb(p.col_bg)}"/>')
            lines.append("</svg>")
            with open(out,"w",encoding="utf-8") as f: f.write("\n".join(lines))

# -------------------------- STEP-Export (single Panel) --------------------------
def export_step_with_freecad(eff_d_map, eff_csk_map, p: Params, out_step):
    try:
        import FreeCAD as App
        import Part
        import math as _m
    except Exception as e:
        raise RuntimeError("FreeCAD-Python-Module not found.") from e

    nx, ny, W, H = build_grid(p)
    t = p.plate_thickness_mm
    if t <= 0: raise ValueError("Plate Thickness has to be > 0.")
    half_ang = _m.radians(p.csk_angle_deg * 0.5)

    base = Part.makeBox(W, H, t)
    cutters = []

    for y in range(ny):
        for x in range(nx):
            cx, cy = cell_center_mm(x, y, p, W)
            r_hole = float(eff_d_map[y,x])*0.5

            cyl = Part.makeCylinder(r_hole, t)
            cyl.Placement.Base = App.Vector(cx, H - cy, 0)
            cutters.append(cyl)

            if p.csk_enable:
                r_top_target = float(eff_csk_map[y,x])*0.5
                r_top_geom_max = r_hole + t * _m.tan(half_ang)
                r_top = max(r_hole, min(r_top_target, r_top_geom_max))
                if r_top > r_hole + 1e-6:
                    h = (r_top - r_hole) / max(1e-9, _m.tan(half_ang))
                    h = min(h, t)
                    if h > 1e-6:
                        cone = Part.makeCone(r_top, r_hole, h)
                        cone.Placement.Base = App.Vector(cx, H - cy, t - h)
                        cutters.append(cone)

    shape = base
    if cutters:
        comp = Part.Compound(cutters)
        shape = base.cut(comp)

    doc = App.newDocument("hole_art_STEP")
    obj = doc.addObject("Part::Feature", "Panel")
    obj.Shape = shape
    doc.recompute()

    try:
        import ImportGui
        ImportGui.export([obj], out_step)
    except Exception:
        obj.Shape.exportStep(out_step)
    finally:
        App.closeDocument(doc.Name)

# -------------------------- STEP-Export (Tiled + Verbinder) --------------------------
def export_step_with_freecad_tiled(eff_d_map, eff_csk_map, p: Params, opts: StepTileOptions, out_step):
    try:
        import FreeCAD as App
        import Part
        import math as _m
    except Exception as e:
        raise RuntimeError("FreeCAD-Python-Module not found.") from e

    nx, ny, W, H = build_grid(p)
    t = p.plate_thickness_mm
    if t <= 0: raise ValueError("Plate Thickness has to be > 0.")
    half_ang = _m.radians(p.csk_angle_deg * 0.5)

    circles = []
    for y in range(ny):
        for x in range(nx):
            cx, cy = cell_center_mm(x, y, p, W)
            Rcs = float(eff_csk_map[y,x])*0.5
            Rh  = float(eff_d_map[y,x])*0.5
            circles.append((cx, cy, Rcs, Rh))

    tiles_x = max(1, int(math.ceil(W / max(1e-6, opts.tile_w_mm)))) if opts.enable else 1
    tiles_y = max(1, int(math.ceil(H / max(1e-6, opts.tile_h_mm)))) if opts.enable else 1

    solids = []

    def tile_bounds(tx, ty):
        ox = tx*opts.tile_w_mm
        oy = ty*opts.tile_h_mm
        w  = min(opts.tile_w_mm, W-ox)
        h  = min(opts.tile_h_mm, H-oy)
        return ox, oy, w, h

    for ty in range(tiles_y):
        for tx in range(tiles_x):
            ox, oy, w_tile, h_tile = tile_bounds(tx, ty)
            base = Part.makeBox(w_tile, h_tile, t)
            base.Placement.Base = App.Vector(ox, H - (oy + h_tile), 0)
            cutters = []

            for (cx,cy,Rcs,Rh) in circles:
                if not (ox <= cx <= ox + w_tile and oy <= cy <= oy + h_tile):
                    continue
                cyl = Part.makeCylinder(Rh, t)
                cyl.Placement.Base = App.Vector(cx, H - cy, 0)
                cutters.append(cyl)
                if p.csk_enable and Rcs > Rh + 1e-6:
                    r_top_target = Rcs
                    r_top_geom_max = Rh + t * _m.tan(half_ang)
                    r_top = max(Rh, min(r_top_target, r_top_geom_max))
                    if r_top > Rh + 1e-6:
                        h = min(t, (r_top - Rh) / max(1e-9, _m.tan(half_ang)))
                        cone = Part.makeCone(r_top, Rh, h)
                        cone.Placement.Base = App.Vector(cx, H - cy, t - h)
                        cutters.append(cone)

            jt = opts.joint_type

            def inner_edge_exists(edge):
                if edge == "N": return ty < tiles_y - 1
                if edge == "S": return ty > 0
                if edge == "W": return tx > 0
                if edge == "E": return tx < tiles_x - 1
                return False

            def add_dowel_series(edge):
                r = opts.dowel_diam_mm * 0.5
                dep= opts.dowel_depth_mm
                sp = max(1.0, opts.dowel_spacing_mm)
                off= opts.dowel_edge_offset_mm
                if edge in ("N","S"):
                    y = oy + (h_tile if edge=="N" else 0.0)
                    x0 = ox + off; x1 = ox + w_tile - off
                    if x1 <= x0: return
                    n = max(1, int(math.floor((x1 - x0)/sp)) + 1)
                    for i in range(n):
                        x = x0 + i*sp
                        cyl = Part.makeCylinder(r, dep)
                        cyl.Placement.Base = App.Vector(x, H - y, 0)
                        cutters.append(cyl)
                else:
                    x = ox + (0.0 if edge=="W" else w_tile)
                    y0 = oy + off; y1 = oy + h_tile - off
                    if y1 <= y0: return
                    n = max(1, int(math.floor((y1 - y0)/sp)) + 1)
                    for i in range(n):
                        y = y0 + i*sp
                        cyl = Part.makeCylinder(r, dep)
                        cyl.Placement.Base = App.Vector(x, H - y, 0)
                        cutters.append(cyl)

            def add_dovetail_series(edge):
                Wt = opts.dt_width_mm
                Dep= opts.dt_depth_mm
                pitch = max(1.0, opts.dt_pitch_mm)
                off= opts.dt_edge_offset_mm
                if edge in ("N","S"):
                    y = oy + (h_tile if edge=="N" else 0.0)
                    x0 = ox + off; x1 = ox + w_tile - off
                    if x1 <= x0: return
                    n = max(1, int(math.floor((x1 - x0)/pitch)) + 1)
                    for i in range(n):
                        xc = x0 + i*pitch
                        box = Part.makeBox(Wt, 2.0, Dep)
                        box.Placement.Base = App.Vector(xc - Wt/2, H - y - 1.0, 0)
                        cutters.append(box)
                else:
                    x = ox + (0.0 if edge=="W" else w_tile)
                    y0 = oy + off; y1 = oy + h_tile - off
                    if y1 <= y0: return
                    n = max(1, int(math.floor((y1 - y0)/pitch)) + 1)
                    for i in range(n):
                        yc = y0 + i*pitch
                        box = Part.makeBox(2.0, Wt, Dep)
                        box.Placement.Base = App.Vector(x - 1.0, H - (yc + Wt/2), 0)
                        cutters.append(box)

            if jt == "dowel":
                for ed in ("N","S","W","E"):
                    if inner_edge_exists(ed):
                        add_dowel_series(ed)
            elif jt == "dovetail":
                for ed in ("N","S","W","E"):
                    if inner_edge_exists(ed):
                        add_dovetail_series(ed)

            if opts.hanger_enable:
                xh = ox + (w_tile/2) + opts.hanger_offset_x_mm
                yh = oy + h_tile - opts.hanger_offset_y_mm
                pocket = Part.makeBox(opts.hanger_w_mm, opts.hanger_h_mm, opts.hanger_depth_mm)
                pocket.Placement.Base = App.Vector(xh - opts.hanger_w_mm/2, H - (yh + opts.hanger_h_mm/2), 0)
                cutters.append(pocket)

            shape = base
            if cutters:
                comp = Part.Compound(cutters)
                shape = base.cut(comp)

            if opts.edge_finish in ("chamfer","fillet") and opts.edge_size_mm > 0:
                try:
                    bb = shape.BoundBox
                    edges = []
                    for e in shape.Edges:
                        eb = e.BoundBox
                        if (abs(eb.XMin - bb.XMin) < 1e-6 or abs(eb.XMax - bb.XMax) < 1e-6 or
                            abs(eb.YMin - bb.YMin) < 1e-6 or abs(eb.YMax - bb.YMax) < 1e-6):
                            edges.append(e)
                    if edges:
                        if opts.edge_finish == "chamfer":
                            shape = Part.makeChamfer(opts.edge_size_mm, shape, edges)
                        else:
                            shape = Part.makeFillet(opts.edge_size_mm, shape, edges)
                except Exception:
                    pass

            solids.append(shape)

    doc = App.newDocument("hole_pattern_STEP_Tiled")
    objs=[]
    for i,sh in enumerate(solids, start=1):
        o = doc.addObject("Part::Feature", f"Tile_{i}")
        o.Shape = sh
        objs.append(o)
    doc.recompute()

    try:
        import ImportGui
        ImportGui.export(objs, out_step)
    except Exception:
        comp = Part.Compound([o.Shape for o in objs])
        tmp = doc.addObject("Part::Feature","CompoundAll"); tmp.Shape = comp; doc.recompute()
        tmp.Shape.exportStep(out_step)
    finally:
        App.closeDocument(doc.Name)

# -------------------------- Pitch Shitf --------------------------
def cell_center_mm(x, y, p: Params, W_total):
    cx = p.margin_mm + (x+0.5)*p.pitch_x_mm
    cy = p.margin_mm + (y+0.5)*p.pitch_y_mm
    if p.stagger and (y % 2 == 1):
        cx += p.pitch_x_mm * p.stagger_ratio
    cx = min(max(p.margin_mm, cx), W_total - p.margin_mm)
    return cx, cy

# -------------------------- Presets Paths --------------------------
def preset_store_path():
    return os.path.join(os.path.expanduser("~"), ".hole_pattern__drillsets.json")
def tiling_preset_store_path():
    return os.path.join(os.path.expanduser("~"), ".hole_pattern__tiling_presets.json")

def load_json_dict(path):
    if not os.path.exists(path): return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
def save_json_dict(path, d: dict):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False

# -------------------------- GUI --------------------------
class AppGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Hole Art Generator")
        self.p = Params()
        self.step_opts = StepTileOptions()
        self.img_path=None
        self.img_w=self.img_h=None
        self._internal=False
        self.d_map=None; self.csk_map=None
        self.preview_imgtk=None

        self.brush_enabled = False
        self.overrides = {}
        self.current_brush_mm = None

        self.export_base_dir = None

        self._pan_active = False

        self._build()

    @staticmethod
    def fval(var) -> float:
        return float(str(var.get()).replace(",", ".").strip())

    # ---------- load/save Drillsets ----------
    def save_drillset_file(self):
        path = filedialog.asksaveasfilename(defaultextension=".drillset",
                                            filetypes=[("Drill_List","*.drillset"),
                                                       ("Text","*.txt"),("all","*.*")])
        if not path: return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.ds_entry.get().strip()+"\n")
            messagebox.showinfo("OK", f"Drilset saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def load_drillset_file(self):
        path = filedialog.askopenfilename(filetypes=[("Drill_List","*.drillset;*.txt"),("all","*.*")])
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                s = f.read().strip()
            self.ds_entry.delete(0, tk.END); self.ds_entry.insert(0, s)
            self.use_ds_var.set(True); self.update_preview()
            messagebox.showinfo("OK", f"Drill List loaded:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    # ---------- Drillset-Presets ----------
    def preset_save_current(self):
        name = simpledialog.askstring("Save Presets ", "Name for Drill-Set:")
        if not name: return
        d = load_json_dict(preset_store_path())
        d[name] = self.ds_entry.get().strip()
        if save_json_dict(preset_store_path(), d):
            messagebox.showinfo("OK", f"Preset '{name}' saved")
        else:
            messagebox.showerror("Error", "Preset could not be saved.")

    def preset_pick_dialog(self, title, items):
        if not items:
            messagebox.showinfo(title, "No Presets available.")
            return None
        win = tk.Toplevel(self.root); win.title(title); win.grab_set(); win.resizable(False, False)
        lb = tk.Listbox(win, width=42, height=min(12, len(items)))
        for k in items: lb.insert(tk.END, k)
        lb.pack(padx=8, pady=8)
        sel = {"value": None}
        def choose():
            idx = lb.curselection()
            if not idx: return
            sel["value"] = items[idx[0]]
            win.destroy()
        tk.Button(win, text="OK", command=choose).pack(pady=(0,8))
        lb.bind("<Double-Button-1>", lambda e: choose())
        win.wait_window()
        return sel["value"]

    def preset_load(self):
        d = load_json_dict(preset_store_path())
        name = self.preset_pick_dialog("load Preset", list(d.keys()))
        if not name: return
        self.ds_entry.delete(0, tk.END); self.ds_entry.insert(0, d[name])
        self.use_ds_var.set(True); self.update_preview()
        messagebox.showinfo("OK", f"Preset '{name}' loaded")

    def preset_delete(self):
        d = load_json_dict(preset_store_path())
        name = self.preset_pick_dialog("Delete Preset", list(d.keys()))
        if not name: return
        if name in d:
            del d[name]
            if save_json_dict(preset_store_path(), d):
                messagebox.showinfo("OK", f"Preset '{name}' deleted")
            else:
                messagebox.showerror("Error", "Preset could not be deleted.")

    # ---------- Tiling-Presets ----------
    def tiling_preset_save(self):
        name = simpledialog.askstring("Save Tiling-Preset ", "Name:")
        if not name: return
        d = load_json_dict(tiling_preset_store_path())
        d[name] = asdict(self.step_opts)
        if save_json_dict(tiling_preset_store_path(), d):
            messagebox.showinfo("OK", f"Tiling-Preset '{name}' saved")
        else:
            messagebox.showerror("Error", "Preset could not be saved.")

    def tiling_preset_load(self):
        d = load_json_dict(tiling_preset_store_path())
        name = self.preset_pick_dialog("Load Tiling-Preset", list(d.keys()))
        if not name: return
        try:
            data = d[name]
            self.step_opts = StepTileOptions(**data)
            messagebox.showinfo("OK", f"Preset '{name}' loaded")
        except Exception as e:
            messagebox.showerror("Error", f"Preset incorrect: {e}")

    def tiling_preset_delete(self):
        d = load_json_dict(tiling_preset_store_path())
        name = self.preset_pick_dialog("Delete Tiling-Preset", list(d.keys()))
        if not name: return
        if name in d:
            del d[name]
            if save_json_dict(tiling_preset_store_path(), d):
                messagebox.showinfo("OK", f"Preset '{name}' deleted")
            else:
                messagebox.showerror("Error", "Preset could not be deleted.")

    # ---------- Batch ----------
    def do_batch(self):
        folder = filedialog.askdirectory(title="Select image folder…")
        if not folder: return
        imgs = [os.path.join(folder, f) for f in os.listdir(folder)
                if f.lower().endswith((".png",".jpg",".jpeg",".bmp"))]
        if not imgs:
            messagebox.showinfo("Batch", "no images found."); return
        p = self.pull()
        count = 0
        for path in imgs:
            try:
                self.img_path = path
                self.img_w, self.img_h = Image.open(path).size
                self.d_map, self.csk_map = generate_maps(path, p)
                eff_d, eff_c = self._effective_maps()
                outdir = self._export_dir_for_image(path)
                os.makedirs(outdir, exist_ok=True)
                base = os.path.splitext(os.path.basename(path))[0]
                export_dxf_r12(eff_d, eff_c, p, os.path.join(outdir, f"{base}.dxf"))
                _, out = export_pdf_or_svg(eff_d, eff_c, p, os.path.join(outdir, f"{base}.pdf"), fallback_svg=True)
                export_csv(eff_d, p, os.path.join(outdir, f"{base}.csv"))
                count += 1
            except Exception as e:
                print("Batch-Error:", path, e)
        messagebox.showinfo("Batch", f"Finished: {count} Data processed.")

    # ---------- Build UI ----------
    def _build(self):
        menubar = tk.Menu(self.root)

        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Export DXF…",  command=self.do_dxf)
        filemenu.add_command(label="Export PDF…",  command=self.do_pdf)
        filemenu.add_command(label="Export SVG…",  command=self.do_svg)
        filemenu.add_command(label="Export CSV…",  command=self.do_csv)
        filemenu.add_separator()
        filemenu.add_command(label="Export STEP…", command=self.do_step)
        filemenu.add_separator()
        filemenu.add_command(label="save Drill List…", command=self.save_drillset_file)
        filemenu.add_command(label="load Drill List…",    command=self.load_drillset_file)
        filemenu.add_separator()
        filemenu.add_command(label="Quit", command=self.root.quit)
        menubar.add_cascade(label="Menu", menu=filemenu)

        drillmenu = tk.Menu(menubar, tearoff=0)
        drillmenu.add_command(label="Save Drill-List as Preset", command=self.preset_save_current)
        drillmenu.add_command(label="Load Preset …", command=self.preset_load)
        drillmenu.add_command(label="Delete Preset…", command=self.preset_delete)
        menubar.add_cascade(label="Dril Lists", menu=drillmenu)

        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_command(label="Zoom +", command=lambda: self.set_zoom(self.p.preview_scale*1.25))
        viewmenu.add_command(label="Zoom –", command=lambda: self.set_zoom(self.p.preview_scale/1.25))
        viewmenu.add_command(label="Zoom 100%", command=lambda: self.set_zoom(0.35))
        menubar.add_cascade(label="View", menu=viewmenu)

        tilingmenu = tk.Menu(menubar, tearoff=0)
        tilingmenu.add_command(label="Options…", command=self.step_tiling_dialog_scrollable)
        tilingmenu.add_separator()
        tilingmenu.add_command(label="Save Preset…", command=self.tiling_preset_save)
        tilingmenu.add_command(label="Load Preset…", command=self.tiling_preset_load)
        tilingmenu.add_command(label="Delete Preset…", command=self.tiling_preset_delete)
        menubar.add_cascade(label="Tiling", menu=tilingmenu)

        self.root.config(menu=menubar)

        toolbar = tk.Frame(self.root, bd=1, relief="Groove")
        b_load = tk.Button(toolbar, text="Load image…", command=self.load_image); b_load.pack(side="left", padx=3, pady=3)
        b_batch = tk.Button(toolbar, text="Batch Folder…", command=self.do_batch); b_batch.pack(side="left", padx=3, pady=3)
        tk.Label(toolbar, text=" | ").pack(side="left")
        b_dxf = tk.Button(toolbar, text="Export DXF",  command=self.do_dxf);   b_dxf.pack(side="left", padx=3, pady=3)
        b_pdf = tk.Button(toolbar, text="Export PDF",  command=self.do_pdf);   b_pdf.pack(side="left", padx=3, pady=3)
        b_svg = tk.Button(toolbar, text="Export SVG",  command=self.do_svg);   b_svg.pack(side="left", padx=3, pady=3)
        b_csv = tk.Button(toolbar, text="Export CSV",  command=self.do_csv);   b_csv.pack(side="left", padx=3, pady=3)
        b_stp = tk.Button(toolbar, text="Export STEP", command=self.do_step);  b_stp.pack(side="left", padx=6, pady=3)
        tk.Label(toolbar, text=" | ").pack(side="left")
        self.brush_btn = tk.Button(toolbar, text="Paintbrush Off", command=self.toggle_brush); self.brush_btn.pack(side="left", padx=3, pady=3)
        self.brush_dd_var = tk.StringVar(value="")
        self.brush_dd = tk.OptionMenu(toolbar, self.brush_dd_var, ())
        self.brush_dd.config(width=12); self.brush_dd.pack(side="left", padx=3, pady=3)
        self.brush_clear_btn = tk.Button(toolbar, text="Set back Overrides", command=self.clear_overrides)
        self.brush_clear_btn.pack(side="left", padx=6, pady=3)
        tk.Label(toolbar, text=" | ").pack(side="left")
        tk.Button(toolbar, text="Zoom +", command=lambda: self.set_zoom(self.p.preview_scale*1.25)).pack(side="left", padx=2)
        tk.Button(toolbar, text="Zoom –", command=lambda: self.set_zoom(self.p.preview_scale/1.25)).pack(side="left", padx=2)
        tk.Button(toolbar, text="100%", command=lambda: self.set_zoom(0.35)).pack(side="left", padx=2)
        tk.Label(toolbar, text=" | ").pack(side="left")
        tk.Label(toolbar, text="Pan: Mouse Wheel | Space+Drag").pack(side="left", padx=2)
        toolbar.pack(fill="x")

        frm = tk.Frame(self.root); frm.pack(fill="both", expand=True, padx=8, pady=8)

        scroll_container = tk.Frame(frm)
        scroll_container.pack(side="left", fill="y", padx=6, pady=4)
        self.left_canvas = tk.Canvas(scroll_container, borderwidth=0, width=340)
        vsb = tk.Scrollbar(scroll_container, orient="vertical", command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.left_canvas.pack(side="left", fill="y", expand=False)

        self.left_inner = tk.Frame(self.left_canvas)
        self.left_canvas.create_window((0,0), window=self.left_inner, anchor="nw")
        self.left_inner.bind("<Configure>", lambda _e=None: self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all")))

        def _on_mousewheel(event):
            delta = -1*(event.delta//120) if event.delta else (1 if event.num==5 else -1)
            self.left_canvas.yview_scroll(delta, "units")
        self.left_canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.left_canvas.bind_all("<Button-4>", _on_mousewheel)
        self.left_canvas.bind_all("<Button-5>", _on_mousewheel)

        right = tk.Frame(frm); right.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(right, bg="#999", cursor="tcross")
        hsb = tk.Scrollbar(right, orient="horizontal", command=self.canvas.xview)
        vsb2= tk.Scrollbar(right, orient="vertical",   command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hsb.set, yscrollcommand=vsb2.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vsb2.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        left = self.left_inner

        sec_dim = tk.LabelFrame(left, text="Size / Aspect ratio")
        sec_dim.pack(fill="x", pady=(0,6))
        self.width_var  = self._spin(sec_dim,"Width (mm)",  self.p.width_mm,  50, 5000, 1, self.on_w)
        self.height_var = self._spin(sec_dim,"Height (mm)",    self.p.height_mm, 50, 5000, 1, self.on_h)
        self.keep_var = tk.BooleanVar(value=self.p.keep_aspect)
        tk.Checkbutton(sec_dim, text="Keep aspect ratio from image",
                       variable=self.keep_var, command=self.on_keep).pack(anchor="w")

        sec_grid = tk.LabelFrame(left, text="Grid / Pitch")
        sec_grid.pack(fill="x", pady=(0,6))
        self.margin_var = self._spin(sec_grid,"Edges (mm)", self.p.margin_mm, 0, 200, 1)
        self.px_var     = self._spin(sec_grid,"Pitch X (mm)", self.p.pitch_x_mm, 1, 100, 0.5)
        self.py_var     = self._spin(sec_grid,"Pitch Y (mm)", self.p.pitch_y_mm, 1, 100, 0.5)
        self.stagger_var = tk.BooleanVar(value=self.p.stagger)
        tk.Checkbutton(sec_grid, text="Offset Rows", variable=self.stagger_var).pack(anchor="w")
        self.stagger_ratio_var = self._spin(sec_grid,"Offset (×Pitch)", self.p.stagger_ratio, 0.0, 1.0, 0.1)

        sec_map = tk.LabelFrame(left, text="Tone Mapping")
        sec_map.pack(fill="x", pady=(0,6))
        self.gamma_var  = self._spin(sec_map,"Contrast", self.p.gamma, 0.2, 5, 0.1)
        self.inv_var   = tk.BooleanVar(value=self.p.invert)
        self.clamp_var = tk.BooleanVar(value=self.p.clamp_edges)
        tk.Checkbutton(sec_map, text="Invert (light/dark)", variable=self.inv_var).pack(anchor="w")

        sec_ds = tk.LabelFrame(left, text="Drill Sizes")
        sec_ds.pack(fill="x", pady=(0,6))
        self.use_ds_var = tk.BooleanVar(value=self.p.use_drillset)

        self.ds_entry = tk.Entry(sec_ds); self.ds_entry.insert(0, self.p.drillset_str); self.ds_entry.pack(fill="x")
        preset_frame = tk.Frame(sec_ds); preset_frame.pack(fill="x", pady=(4,0))
        tk.Label(preset_frame, text="Quick selection:").pack(side="left")
        self.ds_preset_var = tk.StringVar(value="(none)")
        presets = ["(none)","Set1: 3,4,5,6,8,10,12",
                   "Set2: 3,3.5,4,4.5,5,5.5,6,7,8,9,10,11,12",
                   ]
        self.ds_preset = tk.OptionMenu(preset_frame, self.ds_preset_var, *presets, command=self.apply_ds_preset)
        self.ds_preset.pack(side="left", padx=4)

        sec_csk = tk.LabelFrame(left, text="Countersink")
        sec_csk.pack(fill="x", pady=(0,6))
        self.csk_enable_var = tk.BooleanVar(value=self.p.csk_enable)
        tk.Checkbutton(sec_csk, text="Countersink active", variable=self.csk_enable_var).pack(anchor="w")
        self.csk_fac_var = self._spin(sec_csk,"Countersink-Ø Factor", self.p.csk_factor, 1.0, 4.0, 0.1)
        self.web_var     = self._spin(sec_csk,"Minimum bridge (mm)", self.p.min_web_mm, 0.5, 10.0, 0.1)
        self.t_var       = self._spin(sec_csk,"Panel thickness (mm)", self.p.plate_thickness_mm, 0.3, 20.0, 0.1)
        self.csk_ang     = self._spin(sec_csk,"Countersink angle (°)", self.p.csk_angle_deg, 60.0, 120.0, 1)

        sec_col = tk.LabelFrame(left, text="Colors Preview")
        sec_col.pack(fill="x", pady=(0,6))
        self.btn_front = tk.Button(sec_col, text=f"Front Side {self.p.col_front}", command=lambda:self.pick_color("front"))
        self.btn_core  = tk.Button(sec_col, text=f"Core {self.p.col_core}", command=lambda:self.pick_color("core"))
        self.btn_bg    = tk.Button(sec_col, text=f"Background {self.p.col_bg}", command=lambda:self.pick_color("bg"))
        self.btn_front.pack(fill="x"); self.btn_core.pack(fill="x", pady=2); self.btn_bg.pack(fill="x")

        swatch_sets = [
            [(250,250,250),(30,30,30),(220,60,60)],
            [(245,245,245),(10,10,10),(30,144,255)],
            [(240,240,240),(20,20,20),(30,150,90)],
            [(255,248,220),(25,25,25),(180,120,40)],
            [(235,235,235),(30,30,30),(140,140,140)]
        ]
        def make_swatch_row(label, key):
            fr = tk.Frame(sec_col); fr.pack(fill="x", pady=(2,0))
            tk.Label(fr, text=label, width=12).pack(side="left")
            for preset in swatch_sets:
                col = {"front":preset[0],"bg":preset[1],"core":preset[2]}[key]
                btn = tk.Button(fr, width=2, height=1, bg="#%02x%02x%02x"%col,
                                command=lambda c=col,k=key:self._apply_swatch(k,c))
                btn.pack(side="left", padx=2)
        make_swatch_row("Front:", "front")
        make_swatch_row("Background:", "bg")
        make_swatch_row("Core:", "core")

        tk.Button(left, text="Refresh preview", command=self.update_preview).pack(fill="x", pady=(6,4))

        # Canvas-Interaction
        self.canvas.bind("<Button-1>", self.brush_paint)
        self.canvas.bind("<B1-Motion>", self.brush_paint)
        self.canvas.bind("<Button-3>", self.brush_erase)
        self.canvas.bind("<MouseWheel>", self._mouse_zoom)
        self.canvas.bind("<Button-4>", self._mouse_zoom)
        self.canvas.bind("<Button-5>", self._mouse_zoom)
        self.canvas.bind("<ButtonPress-2>", self._pan_start)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.root.bind("<KeyPress-space>", self._space_down)
        self.root.bind("<KeyRelease-space>", self._space_up)

        self.width_var.trace_add("write", lambda *_: self.on_w())
        self.height_var.trace_add("write", lambda *_: self.on_h())

    # ---------- Colour-Swatches ----------
    def _apply_swatch(self, which, rgb):
        if which=="front":
            self.p.col_front = rgb; self.btn_front.config(text=f"Front Side {rgb}")
        elif which=="core":
            self.p.col_core  = rgb; self.btn_core.config(text=f"Core {rgb}")
        else:
            self.p.col_bg    = rgb; self.btn_bg.config(text=f"Background {rgb}")
        self.update_preview()

    # ---------- Tiling-Dialog----------
    def step_tiling_dialog_scrollable(self):
        win = tk.Toplevel(self.root)
        win.title("Tiling & Connector Otions")
        win.grab_set()
        outer = tk.Frame(win); outer.pack(fill="both", expand=True)
        cv = tk.Canvas(outer, borderwidth=0, width=420, height=560)
        vs = tk.Scrollbar(outer, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=vs.set)
        vs.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv)
        cv.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e=None: cv.configure(scrollregion=cv.bbox("all")))

        def spin(fr, label, val, mn, mx, step):
            tk.Label(fr, text=label, anchor="w").pack(anchor="w")
            var = tk.DoubleVar(value=val)
            sb = tk.Spinbox(fr, from_=mn, to=mx, increment=step, textvariable=var, width=12, format="%.1f")
            sb.pack(anchor="w")
            return var, sb

        opts = self.step_opts

        sec_tile = tk.LabelFrame(inner, text="Tiling")
        sec_tile.pack(fill="x", padx=8, pady=6)
        enable_var = tk.BooleanVar(value=opts.enable)
        tk.Checkbutton(sec_tile, text="Activate Tiling (also split PDF/SVG/CSV)", variable=enable_var).pack(anchor="w")
        tw_var, _ = spin(sec_tile, "Tile width (mm)", opts.tile_w_mm, 50, 2000, 1)
        th_var, _ = spin(sec_tile, "Tile height (mm)",  opts.tile_h_mm, 50, 2000, 1)

        sec_joint = tk.LabelFrame(inner, text="Connector (STEP only)")
        sec_joint.pack(fill="x", padx=8, pady=6)
        tk.Label(sec_joint, text="Type:").pack(anchor="w")
        joint_var = tk.StringVar(value=opts.joint_type)
        for t in ("none","dowel","dovetail"):
            tk.Radiobutton(sec_joint, text=t, value=t, variable=joint_var).pack(anchor="w")

        fr_dw = tk.LabelFrame(sec_joint, text="Dowel")
        fr_dw.pack(fill="x", pady=4)
        dw_d_var, _ = spin(fr_dw, "Dowel Diameter (mm) [a]", opts.dowel_diam_mm, 3, 20, 0.5)
        dw_dep_var,_= spin(fr_dw, "Dowel Depth (mm) [b]", opts.dowel_depth_mm, 3, 30, 0.5)
        dw_sp_var, _= spin(fr_dw, "Dowel spacing (mm) [c]", opts.dowel_spacing_mm, 40, 400, 5)
        dw_off_var,_= spin(fr_dw, "Dowel Edge Offset (mm) [d]", opts.dowel_edge_offset_mm, 10, 200, 1)

        fr_dt = tk.LabelFrame(sec_joint, text="Rear dovetails")
        fr_dt.pack(fill="x", pady=4)
        dt_w_var, _ = spin(fr_dt, "pocket width (mm) [A]", opts.dt_width_mm, 6, 60, 1)
        dt_dep_var,_= spin(fr_dt, "pocket depth (mm) [B]", opts.dt_depth_mm, 2, 20, 0.5)
        dt_open_var,_= spin(fr_dt, "opening (mm) [C]", opts.dt_opening_mm, 4, 40, 0.5)
        dt_pitch_var,_=spin(fr_dt, "pitch (mm) [D]", opts.dt_pitch_mm, 40, 400, 5)
        dt_off_var, _= spin(fr_dt, "Edge-Offset (mm) [E]", opts.dt_edge_offset_mm, 10, 200, 1)

        sec_hanger = tk.LabelFrame(inner, text="Hanging bag (back, .STEP only)")
        sec_hanger.pack(fill="x", padx=8, pady=6)
        hanger_en_var = tk.BooleanVar(value=opts.hanger_enable)
        tk.Checkbutton(sec_hanger, text="active", variable=hanger_en_var).pack(anchor="w")
        hg_w_var, _ = spin(sec_hanger, "Width (mm) [H1]", opts.hanger_w_mm, 10, 80, 1)
        hg_h_var, _ = spin(sec_hanger, "Height (mm) [H2]",  opts.hanger_h_mm, 4, 40, 0.5)
        hg_d_var, _ = spin(sec_hanger, "Depth (mm) [H3]",  opts.hanger_depth_mm, 1, 10, 0.5)
        hg_ox_var,_= spin(sec_hanger, "X-Middle-Offset(mm) [H4]", opts.hanger_offset_x_mm, -200, 200, 1)
        hg_oy_var,_= spin(sec_hanger, "Distance from top edge (mm) [H5]",   opts.hanger_offset_y_mm, 5, 200, 1)

        sec_edge = tk.LabelFrame(inner, text="Edge finish (only .STEP)")
        sec_edge.pack(fill="x", padx=8, pady=6)
        edge_var = tk.StringVar(value=opts.edge_finish)
        for t in ("none","chamfer","fillet"):
            tk.Radiobutton(sec_edge, text=t, value=t, variable=edge_var).pack(anchor="w")
        edge_sz_var, _ = spin(sec_edge, "Chamfer/Radius (mm)", opts.edge_size_mm, 0.2, 5.0, 0.1)

        btns = tk.Frame(inner); btns.pack(fill="x", padx=8, pady=8)
        def ok():
            o = self.step_opts
            o.enable = bool(enable_var.get())
            o.tile_w_mm = float(tw_var.get()); o.tile_h_mm = float(th_var.get())
            o.joint_type = joint_var.get()
            o.dowel_diam_mm = float(dw_d_var.get()); o.dowel_depth_mm = float(dw_dep_var.get())
            o.dowel_spacing_mm = float(dw_sp_var.get()); o.dowel_edge_offset_mm = float(dw_off_var.get())
            o.dt_width_mm = float(dt_w_var.get()); o.dt_depth_mm = float(dt_dep_var.get())
            o.dt_opening_mm = float(dt_open_var.get()); o.dt_pitch_mm = float(dt_pitch_var.get())
            o.dt_edge_offset_mm = float(dt_off_var.get())
            o.hanger_enable = bool(hanger_en_var.get())
            o.hanger_w_mm = float(hg_w_var.get()); o.hanger_h_mm = float(hg_h_var.get())
            o.hanger_depth_mm = float(hg_d_var.get()); o.hanger_offset_x_mm = float(hg_ox_var.get())
            o.hanger_offset_y_mm = float(hg_oy_var.get())
            o.edge_finish = edge_var.get(); o.edge_size_mm = float(edge_sz_var.get())
            win.destroy(); messagebox.showinfo("OK","Tiling/Connector adopted.")
        tk.Button(btns, text="OK", command=ok).pack(side="right")
        tk.Button(btns, text="stop", command=win.destroy).pack(side="right", padx=6)

    # ---------- Zoom / Pan ----------
    def set_zoom(self, val):
        self.p.preview_scale = max(0.05, min(5.0, val))
        self.update_preview()
    def _mouse_zoom(self, event):
        if hasattr(event, "delta") and event.delta:
            factor = 1.1 if event.delta > 0 else 1/1.1
        else:
            factor = 1.1 if getattr(event, "num", 0) == 4 else 1/1.1
        self.set_zoom(self.p.preview_scale * factor)
    def _pan_start(self, event):
        self.canvas.scan_mark(event.x, event.y)
    def _pan_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)
    def _space_down(self, _e=None):
        if not self._pan_active:
            self._pan_active = True
            self.canvas.bind("<ButtonPress-1>", self._pan_start)
            self.canvas.bind("<B1-Motion>", self._pan_move)
    def _space_up(self, _e=None):
        if self._pan_active:
            self._pan_active = False
            self.canvas.bind("<ButtonPress-1>", self.brush_paint)
            self.canvas.bind("<B1-Motion>", self.brush_paint)

    # ---------- Brush & Overrides ----------
    def toggle_brush(self):
        self.brush_enabled = not self.brush_enabled
        self.brush_btn.config(text="Paintbrush On" if self.brush_enabled else "Paintbrush Off")
        ds = parse_drillset(self.ds_entry.get()) if self.use_ds_var.get() else []
        menu = self.brush_dd["menu"]; menu.delete(0, "end")
        for v in ds:
            menu.add_command(label=f"{v:.1f} mm", command=lambda val=v: self.brush_dd_var.set(f"{val:.1f}"))
        if ds:
            self.brush_dd_var.set(f"{ds[0]:.1f}"); self.current_brush_mm = ds[0]
        else:
            self.brush_dd_var.set(""); self.current_brush_mm = None

    def clear_overrides(self):
        if self.overrides:
            self.overrides.clear()
            self.update_preview()

    def _canvas_to_cell(self, event):
        if self.d_map is None: return None
        p = self.pull()
        nx, ny, W, H = build_grid(p)
        scale = p.preview_scale
        x_canvas = self.canvas.canvasx(event.x)
        y_canvas = self.canvas.canvasy(event.y)
        x_mm = x_canvas / scale
        y_mm = y_canvas / scale
        x_rel = x_mm - p.margin_mm
        y_rel = y_mm - p.margin_mm
        if x_rel < 0 or y_rel < 0: return None
        y = int(y_rel // p.pitch_y_mm)
        if y < 0 or y >= ny: return None
        x_rel_corr = x_rel - (p.pitch_x_mm * p.stagger_ratio if (p.stagger and (y%2==1)) else 0.0)
        x = int(x_rel_corr // p.pitch_x_mm)
        if x < 0 or x >= nx: return None
        return (x, y)

    def brush_paint(self, event):
        if not self.brush_enabled: return
        cell = self._canvas_to_cell(event)
        if not cell: return
        try:
            val = float(str(self.brush_dd_var.get()).replace(",", "."))
        except:
            return
        x, y = cell
        self.overrides[(y, x)] = round(val,1)
        self.update_preview()

    def brush_erase(self, event):
        if not self.brush_enabled: return
        cell = self._canvas_to_cell(event)
        if not cell: return
        x, y = cell
        if (y, x) in self.overrides:
            del self.overrides[(y, x)]
            self.update_preview()

    # ---------- Helpers ----------
    def apply_ds_preset(self, label):
        if label == "(none)": return
        try: values = label.split(":",1)[1]
        except: values = label
        values = values.strip()
        self.ds_entry.delete(0, tk.END); self.ds_entry.insert(0, values)
        self.use_ds_var.set(True); self.update_preview()

    def _spin(self, parent, label, val, mn, mx, step, cmd=None):
        tk.Label(parent, text=label).pack(anchor="w")
        var = tk.DoubleVar(value=val)
        sp = tk.Spinbox(parent, from_=mn, to=mx, increment=step, textvariable=var, width=14, command=cmd, format="%.1f")
        sp.pack(anchor="w", fill="x")
        return var

    def pull(self)->Params:
        p=self.p; f=self.fval
        p.width_mm  = round(f(self.width_var),1)
        p.height_mm = round(f(self.height_var),1)
        p.keep_aspect = bool(self.keep_var.get())
        p.margin_mm = round(f(self.margin_var),1)
        p.pitch_x_mm = round(f(self.px_var),1)
        p.pitch_y_mm = round(f(self.py_var),1)
        p.stagger = bool(self.stagger_var.get())
        p.stagger_ratio = float(self.stagger_ratio_var.get())
        p.gamma = float(self.gamma_var.get())
        p.invert = bool(self.inv_var.get())
        p.clamp_edges = bool(self.clamp_var.get())
        p.use_drillset = bool(self.use_ds_var.get())
        p.drillset_str = self.ds_entry.get()
        p.csk_enable = bool(self.csk_enable_var.get())
        p.csk_factor = float(self.csk_fac_var.get())
        p.min_web_mm = round(f(self.web_var),1)
        p.plate_thickness_mm = round(f(self.t_var),1)
        p.csk_angle_deg      = float(self.csk_ang.get())
        return p

    def on_keep(self):
        if self.keep_var.get() and self.img_w and self.img_h:
            self._internal=True
            try:
                w=float(self.width_var.get())
                self.height_var.set(round(w*(self.img_h/self.img_w),1))
            finally: self._internal=False
    def on_w(self):
        if self._internal or not self.keep_var.get() or not (self.img_w and self.img_h): return
        try: w=float(self.width_var.get())
        except: return
        self._internal=True
        try: self.height_var.set(round(w*(self.img_h/self.img_w),1))
        finally: self._internal=False
    def on_h(self):
        if self._internal or not self.keep_var.get() or not (self.img_w and self.img_h): return
        try: h=float(self.height_var.get())
        except: return
        self._internal=True
        try: self.width_var.set(round(h*(self.img_w/self.img_h),1))
        finally: self._internal=False

    def pick_color(self, which):
        initial = {"front":self.p.col_front,"core":self.p.col_core,"bg":self.p.col_bg}[which]
        c = colorchooser.askcolor(color="#%02x%02x%02x"%initial, title="select Colour")
        if c[0] is None: return
        rgb = tuple(int(round(v)) for v in c[0])
        if which=="front":
            self.p.col_front = rgb; self.btn_front.config(text=f"Front Side {rgb}")
        elif which=="core":
            self.p.col_core  = rgb; self.btn_core.config(text=f"Core {rgb}")
        else:
            self.p.col_bg    = rgb; self.btn_bg.config(text=f"Background {rgb}")
        self.update_preview()

    def load_image(self):
        path = filedialog.askopenfilename(title="select images",
                                          filetypes=[("images", ("*.png","*.jpg","*.jpeg","*.bmp")), ("all Data","*.*")])
        if not path: return
        self.img_path = path
        try:
            im = Image.open(path); self.img_w,self.img_h = im.size
            if self.keep_var.get(): self.on_keep()
        except Exception as e:
            messagebox.showerror("Image Error", str(e)); self.img_path=None; return
        self.export_base_dir = None
        self.update_preview()

    def _export_dir_for_image(self, img_path):
        if self.export_base_dir: return self.export_base_dir
        base = os.path.splitext(os.path.basename(img_path))[0]
        outdir = os.path.join(os.path.dirname(img_path), base)
        self.export_base_dir = outdir
        return outdir

    def _effective_maps(self):
        if self.d_map is None or self.csk_map is None:
            return None, None
        p = self.pull()
        eff_d = self.d_map.copy()
        eff_c = self.csk_map.copy()
        if self.overrides:
            for (y,x), d in self.overrides.items():
                if 0 <= y < eff_d.shape[0] and 0 <= x < eff_d.shape[1]:
                    eff_d[y,x] = d
                    eff_c[y,x] = limit_csk_diameter(d * max(1.0, p.csk_factor), p) if p.csk_enable else d
        return eff_d, eff_c

    def update_preview(self):
        if not self.img_path:
            return
        p=self.pull()
        try:
            self.d_map, self.csk_map = generate_maps(self.img_path, p)
        except Exception as e:
            messagebox.showerror("Error", str(e)); return

        eff_d, eff_c = self._effective_maps()
        nx, ny, W, H = build_grid(p)
        scale = p.preview_scale
        imgW, imgH = int(W*scale), int(H*scale)
        bg = Image.new("RGB",(imgW,imgH), p.col_front)
        px = bg.load()

        for y in range(ny):
            for x in range(nx):
                cx_mm, cy_mm = cell_center_mm(x, y, p, W)
                cx = int(cx_mm*scale)
                cy = int(cy_mm*scale)
                Rcs = int((eff_c[y,x]*0.5)*scale)
                Rh  = int((eff_d[y,x]*0.5)*scale)
                self._draw_disc(px, imgW, imgH, cx, cy, Rcs, p.col_core)
                self._draw_disc(px, imgW, imgH, cx, cy, Rh,  p.col_bg)

        self.preview_imgtk = ImageTk.PhotoImage(bg)
        self.canvas.delete("all")
        self.canvas.create_image(0,0, anchor="nw", image=self.preview_imgtk)
        self.canvas.config(scrollregion=(0,0,imgW,imgH))

    @staticmethod
    def _draw_disc(px, W,H, cx,cy, R, color):
        if R<=0: return
        r2 = R*R
        x0=max(0,cx-R); x1=min(W-1,cx+R)
        y0=max(0,cy-R); y1=min(H-1,cy+R)  # FIX: cy
        for yy in range(y0,y1+1):
            dy=yy-cy
            rem = r2 - dy*dy
            if rem<0: continue
            rx = int(math.sqrt(rem))
            xa=max(x0,cx-rx); xb=min(x1,cx+rx)
            for xx in range(xa,xb+1):
                px[xx,yy]=color

    # ---------- Export ----------
    def _ensure_maps(self):
        if self.d_map is None or self.csk_map is None:
            if not self.img_path: return False
            self.update_preview()
        return self.d_map is not None

    def _ask_target_in_image_folder(self, ext_default):
        if not self.img_path:
            return filedialog.asksaveasfilename(defaultextension=ext_default)
        outdir = self._export_dir_for_image(self.img_path)
        os.makedirs(outdir, exist_ok=True)
        base = os.path.splitext(os.path.basename(self.img_path))[0]
        return os.path.join(outdir, f"{base}{ext_default}")

    def do_csv(self):
        if not self._ensure_maps(): return
        eff_d, eff_c = self._effective_maps()
        path = self._ask_target_in_image_folder(".csv")
        if not path: return
        try:
            if self.step_opts.enable:
                base_no_ext = os.path.splitext(path)[0]
                export_csv_tiled(eff_d, self.pull(), self.step_opts, base_no_ext)
                messagebox.showinfo("OK", f"CSV Tiles saved (Prefix):\n{base_no_ext}_tile_*.csv")
            else:
                export_csv(eff_d, self.pull(), path)
                messagebox.showinfo("OK", f"CSV saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def do_dxf(self):
        if not self._ensure_maps(): return
        eff_d, eff_c = self._effective_maps()
        path = self._ask_target_in_image_folder(".dxf")
        if not path: return
        try:
            export_dxf_r12(eff_d, eff_c, self.pull(), path)
            messagebox.showinfo("OK", f"DXF saved:\n{path}\nLayer: COUNTERSINK, HOLE")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def do_pdf(self):
        if not self._ensure_maps(): return
        eff_d, eff_c = self._effective_maps()
        path = self._ask_target_in_image_folder(".pdf")
        if not path: return
        try:
            if self.step_opts.enable:
                base_no_ext = os.path.splitext(path)[0]
                export_pdf_tiled(eff_d, eff_c, self.pull(), self.step_opts, base_no_ext)
                messagebox.showinfo("OK", f"PDF Tiles saved (Prefix):\n{base_no_ext}_tile_*.pdf")
            else:
                ok,out = export_pdf_or_svg(eff_d, eff_c, self.pull(), path, fallback_svg=False)
                messagebox.showinfo("OK", f"PDF saved:\n{out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def do_svg(self):
        if not self._ensure_maps(): return
        eff_d, eff_c = self._effective_maps()
        path_pdf = self._ask_target_in_image_folder(".pdf")
        if not path_pdf: return
        try:
            if self.step_opts.enable:
                base_no_ext = os.path.splitext(path_pdf)[0]
                export_svg_tiled(eff_d, eff_c, self.pull(), self.step_opts, base_no_ext)
                messagebox.showinfo("OK", f"SVG Tiles saved (Prefix):\n{base_no_ext}_tile_*.svg")
            else:
                _,out = export_pdf_or_svg(eff_d, eff_c, self.pull(), path_pdf, fallback_svg=True)
                messagebox.showinfo("OK", f"SVG saved:\n{out}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def do_step(self):
        if not self._ensure_maps(): return
        eff_d, eff_c = self._effective_maps()
        path = self._ask_target_in_image_folder(".step")
        if not path: return
        try:
            if getattr(self.step_opts, "enable", False):
                export_step_with_freecad_tiled(eff_d, eff_c, self.pull(), self.step_opts, path)
            else:
                export_step_with_freecad(eff_d, eff_c, self.pull(), path)
            messagebox.showinfo("OK", f"STEP saved:\n{path}")
        except Exception as e:
            messagebox.showerror("STEP-Export Error", str(e))

# -------------------------- Main --------------------------
if __name__=="__main__":
    root = tk.Tk()
    app = AppGUI(root)
    root.geometry("1500x950")
    root.mainloop()
