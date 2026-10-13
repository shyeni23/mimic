"""
Measure Module 1 scan accuracy against ground truth.

Everything in Module 1 except gender is currently unvalidated: body shape,
size, height, skin tone and face shape are geometric rules or a vendored
classifier, and nobody has checked them against measured people. This script
turns a folder of labelled photos into real accuracy numbers.

SETUP
  1. Photograph each volunteer full-body, standing, in the store lighting.
  2. Put the photos in one folder, e.g. data/eval/photos/.
  3. Write data/eval/labels.csv with the real measurements:

       file,height_cm,size,body_shape,face_shape,skin_depth,undertone,gender
       p01.jpg,164,M,pear,oval,medium,warm,female
       p02.jpg,178,L,rectangle,square,light,cool,male

     Leave any cell blank when you don't have that measurement -- it's simply
     excluded from that metric rather than counted as wrong.
     body_shape: pear | rectangle | inverted_triangle | hourglass | apple
     face_shape: oval | round | square | heart | oblong
     skin_depth: fair | light | medium | tan | deep     undertone: warm|cool|neutral

RUN
    python scripts/evaluate_scan_accuracy.py --photos data/eval/photos \\
        --labels data/eval/labels.csv

OUTPUT
  Per-attribute accuracy, mean error for height, a confusion matrix for every
  categorical attribute, and the per-photo detail so you can see WHICH cases
  fail -- the failures are usually more informative than the headline number
  (e.g. "every miss was a dark photo" is an actionable finding).
"""
import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

# Attributes measured, and how each is scored.
NUMERIC = {"height_cm"}
CATEGORICAL = ["body_shape", "face_shape", "size", "skin_depth", "undertone", "gender"]
# Height is an estimate from an assumed average face length -- this is the
# tolerance the project treats as "right" for a clothing-size purpose.
HEIGHT_TOLERANCE_CM = 5.0


def analyse(image_path: Path) -> dict:
    """Run the real scan pipeline on one photo -- the same code /api/vision/scan
    calls, so the numbers reflect production behaviour, not a reimplementation."""
    from app.services.vision.landmarks import extract_pose_landmarks, extract_face_landmarks
    from app.services.vision.body_shape import classify_body_shape, estimate_body_size
    from app.services.vision.face_shape import classify_face_shape
    from app.services.vision.skin_tone import extract_skin_tone
    from app.services.vision.height_estimate import estimate_height_from_camera
    from app.services.vision.gender_detect import detect_gender

    img = cv2.imread(str(image_path))
    if img is None:
        return {"error": "could not read image"}

    pose = extract_pose_landmarks(img) or []
    face = extract_face_landmarks(img) or []
    out = {}

    try:
        out["body_shape"] = classify_body_shape(pose).get("body_shape")
    except Exception as e:
        out["body_shape_error"] = str(e)
    try:
        out["size"] = estimate_body_size(pose, img.shape[0]).get("body_size_estimate")
    except Exception as e:
        out["size_error"] = str(e)
    try:
        out["face_shape"] = classify_face_shape(face, img).get("face_shape")
    except Exception as e:
        out["face_shape_error"] = str(e)
    try:
        tone = extract_skin_tone(img, face)
        out["skin_depth"] = tone.get("depth")
        out["undertone"] = tone.get("undertone")
    except Exception as e:
        out["skin_tone_error"] = str(e)
    try:
        out["height_cm"] = estimate_height_from_camera(pose, None, face_landmarks=face).get("height_cm")
    except Exception as e:
        out["height_error"] = str(e)
    try:
        out["gender"] = detect_gender(img, face).get("gender")
    except Exception as e:
        out["gender_error"] = str(e)

    # Brightness, so a bad run can be explained ("every miss was a dark photo").
    out["_frame_brightness"] = round(float(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).mean()), 1)
    return out


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    if not v:
        return None
    # The frontend calls oblong "long"; treat them as the same class.
    return {"long": "oblong", "man": "male", "woman": "female"}.get(v, v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--photos", required=True, help="Folder of labelled photos")
    ap.add_argument("--labels", required=True, help="CSV of ground-truth measurements")
    ap.add_argument("--json-out", help="Also write the full per-photo results here")
    args = ap.parse_args()

    photos_dir = Path(args.photos)
    rows = list(csv.DictReader(open(args.labels, encoding="utf-8-sig")))
    if not rows:
        print(f"No rows in {args.labels}")
        return 1

    print(f"Evaluating {len(rows)} photos from {photos_dir}\n")
    hits = defaultdict(int)
    totals = defaultdict(int)
    height_errors = []
    confusion = defaultdict(Counter)   # attr -> Counter[(truth, predicted)]
    details = []

    for i, row in enumerate(rows, 1):
        path = photos_dir / row["file"]
        if not path.exists():
            print(f"  [{i}/{len(rows)}] {row['file']}: MISSING FILE -- skipped")
            continue
        got = analyse(path)
        detail = {"file": row["file"], "brightness": got.get("_frame_brightness"), "results": {}}

        for attr in CATEGORICAL:
            truth = _norm(row.get(attr))
            pred = _norm(got.get(attr))
            if truth is None:
                continue                      # not measured -- excluded, not wrong
            totals[attr] += 1
            ok = (pred == truth)
            hits[attr] += ok
            confusion[attr][(truth, pred or "none")] += 1
            detail["results"][attr] = {"truth": truth, "predicted": pred, "correct": ok}

        truth_h = row.get("height_cm", "").strip()
        pred_h = got.get("height_cm")
        if truth_h and pred_h:
            err = abs(float(pred_h) - float(truth_h))
            height_errors.append(err)
            totals["height_cm"] += 1
            hits["height_cm"] += err <= HEIGHT_TOLERANCE_CM
            detail["results"]["height_cm"] = {
                "truth": float(truth_h), "predicted": round(float(pred_h), 1), "error_cm": round(err, 1),
            }
        details.append(detail)
        flags = "".join("." if r.get("correct", True) else "X" for r in detail["results"].values())
        print(f"  [{i}/{len(rows)}] {row['file']:<22} {flags}  (brightness {detail['brightness']})")

    # ---------------- Report
    print("\n" + "=" * 62)
    print("ACCURACY")
    print("=" * 62)
    for attr in CATEGORICAL:
        if totals[attr]:
            pct = 100 * hits[attr] / totals[attr]
            print(f"  {attr:<14} {hits[attr]:>3}/{totals[attr]:<3}  {pct:5.1f}%")
    if height_errors:
        pct = 100 * hits["height_cm"] / totals["height_cm"]
        print(f"  {'height_cm':<14} {hits['height_cm']:>3}/{totals['height_cm']:<3}  {pct:5.1f}%"
              f"   (within {HEIGHT_TOLERANCE_CM:.0f} cm)")
        print(f"  {'':<14} mean error {np.mean(height_errors):.1f} cm, "
              f"median {np.median(height_errors):.1f} cm, worst {max(height_errors):.1f} cm")

    print("\n" + "=" * 62)
    print("WHERE IT GOES WRONG  (truth -> predicted, only the mistakes)")
    print("=" * 62)
    for attr in CATEGORICAL:
        wrong = {k: v for k, v in confusion[attr].items() if k[0] != k[1]}
        if wrong:
            print(f"  {attr}:")
            for (truth, pred), n in sorted(wrong.items(), key=lambda kv: -kv[1]):
                print(f"      {truth:<18} -> {pred:<18} x{n}")

    dark = [d for d in details if (d["brightness"] or 255) < 70]
    if dark:
        print(f"\n  NOTE: {len(dark)} photo(s) were dark (brightness < 70). Skin tone, "
              f"gender and face shape all degrade there -- check whether the misses cluster here.")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(details, indent=2), encoding="utf-8")
        print(f"\nPer-photo detail written to {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
