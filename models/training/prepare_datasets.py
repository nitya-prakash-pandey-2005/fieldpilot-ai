#!/usr/bin/env python
"""
T0 — Dataset download + harmonization into the FieldPilot-28 taxonomy.

Merges every source dataset listed in taxonomy.yaml into one Ultralytics-format
detection dataset at <out>/fieldpilot<N>/, with a SCENE-AWARE train/val/test
split (see --help for why that matters).

Usage
-----
    export ROBOFLOW_API_KEY=...
    python models/training/prepare_datasets.py \
        --out data/training \
        --datasets D1,D5,D8                 # roboflow ones need no manual download
    # then, for the manually-downloaded sets:
    python models/training/prepare_datasets.py \
        --out data/training --datasets D2,D3,D4,D6 \
        --d2-root /data/SH17 --d3-root /data/MOCS --d4-root /data/ACID --d6-root /data/CHV

Runs incrementally: re-running with a new --datasets list adds to the existing
output rather than rebuilding, so you can pull sets in as you obtain them.
Pass --rebuild to start clean.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# A frame index at the end of a filename ("site3_frame_0142.jpg", "clip7-0142.jpg")
# is the giveaway that consecutive images come from one video. Everything sharing
# a stem-prefix once that index is stripped is treated as one scene.
_FRAME_SUFFIX = re.compile(r"[-_ ]?(frame)?[-_ ]?\d{1,6}$", re.IGNORECASE)
# Roboflow appends a content hash to every exported filename; strip it first.
_RF_HASH = re.compile(r"[._]rf[._][0-9a-f]{6,}$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# taxonomy
# ---------------------------------------------------------------------------

def load_taxonomy(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        tax = yaml.safe_load(f)
    tax["classes"] = {int(k): v for k, v in tax["classes"].items()}
    return tax


def _norm_label(s: str) -> str:
    """Case/separator-insensitive label key so 'NO-Hardhat', 'no_hardhat' and
    'No Hardhat' all resolve to the same mapping entry."""
    return re.sub(r"[\s_\-]+", "", str(s).strip().lower())


def build_mapper(source_cfg: dict, source_id: str):
    """Returns fn(label:str) -> int|None. Raises on an unmapped label so that a
    dataset changing its label set fails loudly instead of silently dropping
    annotations (which looks identical to 'the class is just rare')."""
    table = {_norm_label(k): v for k, v in (source_cfg.get("mapping") or {}).items()}

    def mapper(label: str):
        key = _norm_label(label)
        if key not in table:
            raise KeyError(
                f"[{source_id}] label {label!r} is not in taxonomy.yaml's mapping. "
                f"Add it (or map it to null to drop it deliberately). "
                f"Known: {sorted(table)}"
            )
        return table[key]

    return mapper


# ---------------------------------------------------------------------------
# scene keys and splitting
# ---------------------------------------------------------------------------

def scene_key(source_id: str, img_path: Path) -> str:
    """Group near-duplicate frames so they can't straddle the split boundary.

    MOCS and ACID are video-derived: a random per-image split puts frame 0141 in
    train and 0142 in val, which leaks and inflates mAP by 5-10 points. Grouping
    by stripped stem keeps whole clips on one side.
    """
    stem = _RF_HASH.sub("", img_path.stem)
    stem = _FRAME_SUFFIX.sub("", stem)
    if not stem:                       # filename was nothing but digits
        stem = img_path.parent.name
    return f"{source_id}/{stem}"


def assign_split(key: str, ratios=(0.70, 0.15, 0.15)) -> str:
    """Deterministic hash-based assignment — stable across re-runs and across
    machines, so an incremental run never reshuffles previously-placed scenes."""
    h = int(hashlib.md5(key.encode("utf-8")).hexdigest()[:8], 16) / 0xFFFFFFFF
    if h < ratios[0]:
        return "train"
    if h < ratios[0] + ratios[1]:
        return "val"
    return "test"


# ---------------------------------------------------------------------------
# annotation readers — each yields (image_path, [(label, xc, yc, w, h) normalized])
# ---------------------------------------------------------------------------

def _yolo_names(root: Path) -> dict[int, str]:
    """Read class names from a dataset's data.yaml so integer YOLO ids can be
    resolved back to strings before remapping."""
    for cand in ("data.yaml", "dataset.yaml", "data.yml"):
        p = root / cand
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                d = yaml.safe_load(f)
            names = d.get("names")
            if isinstance(names, dict):
                return {int(k): v for k, v in names.items()}
            if isinstance(names, list):
                return dict(enumerate(names))
    return {}


def read_yolo(root: Path):
    names = _yolo_names(root)
    for img in sorted(root.rglob("*")):
        if img.suffix.lower() not in IMG_EXTS:
            continue
        lbl = Path(str(img).replace(f"{os.sep}images{os.sep}", f"{os.sep}labels{os.sep}"))
        lbl = lbl.with_suffix(".txt")
        if not lbl.exists():
            continue
        boxes = []
        for line in lbl.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            cid = int(float(parts[0]))
            boxes.append((names.get(cid, str(cid)), *map(float, parts[1:5])))
        yield img, boxes


def read_coco(root: Path):
    """MOCS ships COCO json. Handles one or many annotation files."""
    for ann_file in sorted(root.rglob("*.json")):
        try:
            data = json.loads(ann_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        images = data.get("images")
        if not images or "annotations" not in data:
            continue
        cats = {c["id"]: c["name"] for c in data.get("categories", [])}
        by_img = defaultdict(list)
        for a in data["annotations"]:
            by_img[a["image_id"]].append(a)
        # images live next to, or one dir under, the annotation file
        search_roots = [ann_file.parent, *[p for p in ann_file.parent.parent.iterdir() if p.is_dir()]]
        for im in images:
            fname = Path(im["file_name"]).name
            path = next((r / fname for r in search_roots if (r / fname).exists()), None)
            if path is None:
                continue
            W, H = float(im["width"]), float(im["height"])
            boxes = []
            for a in by_img.get(im["id"], []):
                x, y, w, h = a["bbox"]
                if w <= 0 or h <= 0:
                    continue
                boxes.append((cats.get(a["category_id"], "unknown"),
                              (x + w / 2) / W, (y + h / 2) / H, w / W, h / H))
            yield path, boxes


def read_voc(root: Path):
    """ACID ships Pascal VOC xml."""
    for xml_path in sorted(root.rglob("*.xml")):
        try:
            tree = ET.parse(xml_path)
        except ET.ParseError:
            continue
        r = tree.getroot()
        size = r.find("size")
        if size is None:
            continue
        W, H = float(size.findtext("width", 0)), float(size.findtext("height", 0))
        if W <= 0 or H <= 0:
            continue
        img = next((p for p in (xml_path.with_suffix(e) for e in IMG_EXTS) if p.exists()), None)
        if img is None:
            stem = xml_path.stem
            img = next((p for p in root.rglob(f"{stem}.*") if p.suffix.lower() in IMG_EXTS), None)
        if img is None:
            continue
        boxes = []
        for obj in r.findall("object"):
            bb = obj.find("bndbox")
            if bb is None:
                continue
            x1, y1 = float(bb.findtext("xmin", 0)), float(bb.findtext("ymin", 0))
            x2, y2 = float(bb.findtext("xmax", 0)), float(bb.findtext("ymax", 0))
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append((obj.findtext("name", "unknown"),
                          (x1 + x2) / 2 / W, (y1 + y2) / 2 / H, (x2 - x1) / W, (y2 - y1) / H))
        yield img, boxes


READERS = {"yolo": read_yolo, "yolov8": read_yolo, "coco": read_coco, "voc": read_voc}


# ---------------------------------------------------------------------------
# roboflow acquisition
# ---------------------------------------------------------------------------

def fetch_roboflow(cfg: dict, cache: Path, source_id: str) -> list[Path]:
    key = os.getenv("ROBOFLOW_API_KEY")
    if not key:
        print(f"  [{source_id}] SKIPPED — ROBOFLOW_API_KEY not set", file=sys.stderr)
        return []
    try:
        from roboflow import Roboflow
    except ImportError:
        print(f"  [{source_id}] SKIPPED — `pip install roboflow`", file=sys.stderr)
        return []

    specs = cfg.get("projects") or [{k: cfg[k] for k in ("workspace", "project", "version")}]
    rf = Roboflow(api_key=key)
    roots = []
    for spec in specs:
        dest = cache / f"{source_id}_{spec['project']}_v{spec['version']}"
        if dest.exists():
            print(f"  [{source_id}] cached: {dest.name}")
            roots.append(dest)
            continue
        try:
            print(f"  [{source_id}] downloading {spec['workspace']}/{spec['project']} v{spec['version']}…")
            ds = (rf.workspace(spec["workspace"])
                    .project(spec["project"])
                    .version(spec["version"])
                    .download(cfg.get("format", "yolov8"), location=str(dest)))
            roots.append(Path(ds.location))
        except Exception as e:
            # A Universe project can be renamed or made private at any time —
            # that shouldn't kill a 6-dataset build.
            print(f"  [{source_id}] FAILED {spec['project']}: {e}", file=sys.stderr)
    return roots


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="data/training", help="output root")
    # D1,D5,D8 are the Roboflow-fetchable core (no manual download). D9/D10 add
    # trench and ladder — the two classes Agent 11's Fatal Four rules need, and
    # the reason the taxonomy went 28 -> 30. They are in the default because
    # omitting them trains a detector that CANNOT support those rules, and that
    # is a silent capability gap rather than a visible one.
    # D2/D3/D4/D6/D7 still need --dN-root; they are opt-in by design.
    ap.add_argument("--datasets", default="D1,D5,D8,D9,D10",
                    help="comma-separated ids from taxonomy.yaml")
    ap.add_argument("--taxonomy", default=str(HERE / "taxonomy.yaml"))
    ap.add_argument("--cache", default="data/training/_downloads")
    ap.add_argument("--rebuild", action="store_true", help="wipe output before building")
    ap.add_argument("--sparse-threshold", type=int, default=200,
                    help="warn when a class has fewer instances than this")
    ap.add_argument("--copy", action="store_true",
                    help="copy images instead of hardlinking (slower, 50GB+; use across filesystems)")
    for d in ("d2", "d3", "d4", "d6", "d7"):
        ap.add_argument(f"--{d}-root", default=None, help=f"local extracted root for {d.upper()}")
    args = ap.parse_args()

    tax = load_taxonomy(Path(args.taxonomy))
    classes = tax["classes"]
    # Named from the taxonomy, not hardcoded: the class count is now a
    # variable (28 -> 30 when trench/ladder landed) and a directory called
    # fieldpilot28 holding 30 classes is precisely the drift that makes a
    # later reader trust the wrong number.
    ds_name = f"fieldpilot{len(classes)}"
    out_root = Path(args.out) / ds_name
    cache = Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    if args.rebuild and out_root.exists():
        shutil.rmtree(out_root)
    for split in ("train", "val", "test"):
        (out_root / split / "images").mkdir(parents=True, exist_ok=True)
        (out_root / split / "labels").mkdir(parents=True, exist_ok=True)

    counts = Counter()               # class id -> instance count
    per_split = Counter()            # split -> image count
    per_source = Counter()           # source -> image count
    dropped = Counter()              # source -> annotations deliberately dropped
    scenes: dict[str, str] = {}      # scene key -> split (for the report)

    for source_id in [s.strip() for s in args.datasets.split(",") if s.strip()]:
        cfg = tax["sources"].get(source_id)
        if not cfg:
            print(f"[{source_id}] not defined in taxonomy.yaml — skipping", file=sys.stderr)
            continue

        print(f"\n=== {source_id} ({cfg['kind']}, {cfg['format']}) ===")

        if cfg["kind"].startswith("roboflow"):
            roots = fetch_roboflow(cfg, cache, source_id)
        else:
            manual = getattr(args, f"{source_id.lower()}_root", None)
            if not manual:
                print(f"  SKIPPED — needs --{source_id.lower()}-root "
                      f"(download it manually, see docs/TRAINING_PLAN.md §2.1)", file=sys.stderr)
                continue
            root = Path(manual)
            if not root.exists():
                print(f"  SKIPPED — {root} does not exist", file=sys.stderr)
                continue
            roots = [root]

        if not roots:
            continue

        mapper = build_mapper(cfg, source_id)
        reader = READERS[cfg["format"]]

        for root in roots:
            for img_path, boxes in reader(root):
                remapped = []
                for label, xc, yc, w, h in boxes:
                    try:
                        target = mapper(label)
                    except KeyError as e:
                        print(f"\n{e}\n", file=sys.stderr)
                        return 2
                    if target is None:
                        dropped[source_id] += 1
                        continue
                    # clamp — a few source sets ship boxes a hair outside [0,1]
                    xc, yc = min(max(xc, 0.0), 1.0), min(max(yc, 0.0), 1.0)
                    w, h = min(max(w, 0.0), 1.0), min(max(h, 0.0), 1.0)
                    if w <= 1e-4 or h <= 1e-4:
                        continue
                    remapped.append((target, xc, yc, w, h))
                    counts[target] += 1

                # Keep negatives (images with zero remaining boxes) at a low rate —
                # they teach the model what "nothing here" looks like, but a flood
                # of them (e.g. all of MOCS after dropping unmapped classes) skews
                # training toward predicting nothing.
                if not remapped and random.Random(str(img_path)).random() > 0.05:
                    continue

                key = scene_key(source_id, img_path)
                split = assign_split(key)
                scenes[key] = split

                stem = f"{source_id}_{hashlib.md5(str(img_path).encode()).hexdigest()[:12]}"
                dst_img = out_root / split / "images" / f"{stem}{img_path.suffix.lower()}"
                dst_lbl = out_root / split / "labels" / f"{stem}.txt"

                if not dst_img.exists():
                    try:
                        if args.copy:
                            shutil.copy2(img_path, dst_img)
                        else:
                            os.link(img_path, dst_img)   # hardlink: no extra disk
                    except OSError:
                        shutil.copy2(img_path, dst_img)  # cross-filesystem fallback
                dst_lbl.write_text(
                    "".join(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n" for c, x, y, w, h in remapped),
                    encoding="utf-8",
                )
                per_split[split] += 1
                per_source[source_id] += 1

    # ---- dataset yaml -----------------------------------------------------
    yaml_path = out_root / f"{ds_name}.yaml"
    yaml_path.write_text(yaml.safe_dump({
        "path": str(out_root.resolve()),
        "train": "train/images",
        "val": "val/images",
        "test": "test/images",
        "nc": len(classes),
        "names": {i: classes[i] for i in sorted(classes)},
    }, sort_keys=False), encoding="utf-8")

    # ---- report -----------------------------------------------------------
    total_imgs = sum(per_split.values())
    total_anns = sum(counts.values())
    print("\n" + "=" * 66)
    print(f"FieldPilot-28 built at {out_root}")
    print("=" * 66)
    print(f"  images      : {total_imgs:,}   (train {per_split['train']:,} / "
          f"val {per_split['val']:,} / test {per_split['test']:,})")
    print(f"  annotations : {total_anns:,}")
    print(f"  scenes      : {len(scenes):,}")
    print(f"  per source  : {dict(per_source)}")
    if dropped:
        print(f"  dropped anns: {dict(dropped)}  (deliberate — mapped to null)")

    print("\n  class histogram:")
    known_sparse = set(tax.get("known_sparse", []))
    unexpected = []
    for cid in sorted(classes):
        n = counts.get(cid, 0)
        bar = "#" * min(int(n / max(total_anns, 1) * 300), 50)
        flag = ""
        if n < args.sparse_threshold:
            flag = "  <- sparse (known)" if cid in known_sparse else "  <- SPARSE, UNEXPECTED"
            if cid not in known_sparse:
                unexpected.append((cid, classes[cid], n))
        print(f"    {cid:2d} {classes[cid]:<18} {n:7,}  {bar}{flag}")

    if unexpected:
        print("\n  ⚠ These classes are starved but weren't expected to be. That is")
        print("    almost always a taxonomy mapping bug, not a data gap — check")
        print("    taxonomy.yaml's mapping block for the source that should")
        print("    provide them before you start a 16-hour training run:")
        for cid, name, n in unexpected:
            print(f"      {cid:2d} {name}: {n} instances")

    # histogram png for the deck (§10 of TRAINING_PLAN)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        ids = sorted(classes)
        fig, ax = plt.subplots(figsize=(11, 6))
        ax.bar([classes[i] for i in ids], [counts.get(i, 0) for i in ids], color="#33B5E5")
        ax.set_ylabel("instances")
        ax.set_title(f"FieldPilot-28 composition — {total_imgs:,} images, {total_anns:,} annotations")
        plt.xticks(rotation=75, ha="right")
        plt.tight_layout()
        dest = Path("models/evaluation/class_histogram.png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(dest, dpi=140)
        print(f"\n  histogram png -> {dest}")
    except ImportError:
        pass

    print(f"\n  next: python models/training/train_detector.py --data {yaml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
