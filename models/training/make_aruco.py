#!/usr/bin/env python
"""
Generate a printable ArUco calibration marker for Agent 2.

    python models/training/make_aruco.py --id 0 --size-mm 100 --out data/aruco_100mm.png

Print at 100% scale (NOT "fit to page" — that silently rescales it and every
measurement inherits the error), then measure the printed black square with a
ruler and confirm it is the size you asked for. Mount it on rigid card: a curled
sheet is the single largest source of error in the ArUco path, because the plane
homography assumes the marker is flat.

The default DICT_4X4_50 / id 0 / 100mm matches agents/measurement/calibration.py's
defaults, so a marker printed with no arguments works out of the box.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

DPI = 300
MM_PER_INCH = 25.4


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--size-mm", type=float, default=100.0)
    ap.add_argument("--dict", default="DICT_4X4_50")
    ap.add_argument("--out", default="data/aruco_100mm.png")
    ap.add_argument("--dpi", type=int, default=DPI)
    args = ap.parse_args()

    dictionary = cv2.aruco.getPredefinedDictionary(
        getattr(cv2.aruco, args.dict, cv2.aruco.DICT_4X4_50))

    side_px = int(round(args.size_mm / MM_PER_INCH * args.dpi))
    marker = cv2.aruco.generateImageMarker(dictionary, args.id, side_px)

    # White quiet zone — the detector needs it, and it gives you somewhere to
    # write the size so a marker found on site can't be used at the wrong scale.
    pad = int(side_px * 0.22)
    canvas = np.full((side_px + 2 * pad, side_px + 2 * pad), 255, dtype=np.uint8)
    canvas[pad:pad + side_px, pad:pad + side_px] = marker

    label = f"FieldPilot AI  |  {args.dict} id={args.id}  |  {args.size_mm:g} mm  |  PRINT AT 100%"
    cv2.putText(canvas, label, (pad // 2, canvas.shape[0] - pad // 3),
                cv2.FONT_HERSHEY_SIMPLEX, side_px / 1400.0, 0, 2, cv2.LINE_AA)

    # Corner ticks so you can verify the printed size with a ruler.
    t = int(side_px * 0.05)
    for (cx, cy) in ((pad, pad), (pad + side_px, pad),
                     (pad, pad + side_px), (pad + side_px, pad + side_px)):
        cv2.line(canvas, (cx - t, cy), (cx + t, cy), 0, 1)
        cv2.line(canvas, (cx, cy - t), (cx, cy + t), 0, 1)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), canvas)

    print(f"✔ {out}")
    print(f"  {args.dict} id={args.id}, {args.size_mm:g}mm at {args.dpi} DPI "
          f"({canvas.shape[1]}x{canvas.shape[0]} px)")
    print(f"  Set in .env if you change these:  ARUCO_DICT={args.dict}  "
          f"ARUCO_MARKER_MM={args.size_mm:g}")
    print("  Print at 100% scale, verify the black square measures "
          f"{args.size_mm:g}mm edge-to-edge, mount on rigid card.")


if __name__ == "__main__":
    main()
