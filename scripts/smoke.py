"""Per-module smoke test using the labeled images in ./Images.

Labels (from Image_categories.txt):
  out-of-focus subject: DSC_0001, DSC_0027
  eyes closed:          DSC_0005, DSC_0009, DSC_0010, DSC_0012, DSC_0041
  blurry:               DSC_0038
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "Images"

LABELED = {
    "out_of_focus_subject": ["DSC_0001.JPG", "DSC_0027.JPG"],
    "eyes_closed": ["DSC_0005.JPG", "DSC_0009.JPG", "DSC_0010.JPG", "DSC_0012.JPG", "DSC_0041.JPG"],
    "blurry": ["DSC_0038.JPG"],
}
# A few presumed-sharp controls — anything not on the bad list.
CONTROLS = ["DSC_0015.JPG", "DSC_0020.JPG", "DSC_0030.JPG"]


def banner(label: str) -> None:
    print(f"\n=== {label} ===")


def t(fn, *args, **kwargs):
    s = time.perf_counter()
    out = fn(*args, **kwargs)
    return out, (time.perf_counter() - s) * 1000


def test_decode() -> None:
    from blurdetector import decode

    banner("decode.py")
    for name in ["DSC_0001.JPG", "DSC_0038.JPG"]:
        img, ms = t(decode.decode, IMG / name)
        print(f"  {name}: {img.rgb.shape} dtype={img.rgb.dtype} kind={img.kind} "
              f"src={img.source_w}x{img.source_h}  [{ms:.0f} ms]")


def test_exif() -> None:
    from blurdetector import exif

    banner("exif.py")
    for name in ["DSC_0001.JPG", "DSC_0038.JPG"]:
        e, ms = t(exif.read_exif, IMG / name)
        print(f"  {name}: {e.camera_make} {e.camera_model} "
              f"f/{e.f_number} 1/{int(1/e.exposure_time) if e.exposure_time else '?'} "
              f"iso{e.iso} {e.focal_length_mm}mm  capture={e.capture_time}  [{ms:.0f} ms]")


def test_sharpness() -> None:
    from blurdetector import decode
    from blurdetector.metrics import sharpness

    banner("sharpness.py — expect blurry < controls")
    cases = LABELED["blurry"] + LABELED["out_of_focus_subject"] + CONTROLS
    for name in cases:
        rgb = decode.decode(IMG / name).rgb
        s, ms = t(sharpness.measure, rgb)
        tag = "(blurry)" if name in LABELED["blurry"] else \
              "(OOF-subj)" if name in LABELED["out_of_focus_subject"] else "(control)"
        print(f"  {name} {tag}: lap={s.laplacian_var:.1f} ten={s.tenengrad:.0f} "
              f"aniso={s.fft_anisotropy:.2f} score={s.score:.3f}  [{ms:.0f} ms]")


def test_subject_and_subject_sharpness() -> None:
    from blurdetector import decode
    from blurdetector.metrics import sharpness, subject

    banner("subject.py + subject-aware sharpness")
    cases = LABELED["out_of_focus_subject"] + LABELED["eyes_closed"][:2] + CONTROLS[:1]
    for name in cases:
        rgb = decode.decode(IMG / name).rgb
        subs, ms = t(subject.detect_subjects, rgb)
        primary = subject.primary_bbox(subs)
        s_global = sharpness.measure(rgb)
        s_subj = sharpness.measure(rgb, primary) if primary else None
        print(f"  {name}: {len(subs)} subjects "
              f"(primary={subs[0].kind if subs else 'none'})  [{ms:.0f} ms]")
        print(f"     global  score={s_global.score:.3f}  lap={s_global.laplacian_var:.1f}")
        if s_subj:
            print(f"     subject score={s_subj.score:.3f}  lap={s_subj.laplacian_var:.1f}")


def test_eyes() -> None:
    from blurdetector import decode
    from blurdetector.metrics import eyes

    banner("eyes.py — expect any_closed=True on labeled set")
    cases = LABELED["eyes_closed"] + CONTROLS[:2]
    for name in cases:
        rgb = decode.decode(IMG / name).rgb
        r, ms = t(eyes.measure, rgb)
        tag = "(closed)" if name in LABELED["eyes_closed"] else "(control)"
        ears = ", ".join(f"{e:.2f}" for e in r.ears)
        print(f"  {name} {tag}: faces={r.faces} ears=[{ears}] "
              f"min={r.min_ear} any_closed={r.any_closed}  [{ms:.0f} ms]")


def test_exposure_noise_composition() -> None:
    from blurdetector import decode
    from blurdetector.metrics import composition, exposure, noise, subject

    banner("exposure.py / noise.py / composition.py")
    for name in ["DSC_0001.JPG", "DSC_0015.JPG"]:
        rgb = decode.decode(IMG / name).rgb
        ex, ms_e = t(exposure.measure, rgb)
        sigma, ms_n = t(noise.estimate_sigma, rgb)
        subs = subject.detect_subjects(rgb)
        cp, ms_c = t(composition.measure, rgb, subject.primary_bbox(subs))
        print(f"  {name}: mean_luma={ex.mean_luma:.0f} clipHi={ex.clipped_highlight:.3f} "
              f"clipLo={ex.clipped_shadow:.3f} under={ex.underexposed} over={ex.overexposed}  "
              f"[exp {ms_e:.0f} ms]")
        print(f"     noise σ={sigma:.2f}  [{ms_n:.0f} ms]")
        print(f"     horizon_tilt={cp.horizon_tilt_deg} thirds_offset={cp.thirds_offset}  "
              f"[comp {ms_c:.0f} ms]")


def test_phash() -> None:
    from blurdetector import decode
    from blurdetector.metrics import phash

    banner("phash.py")
    p1 = phash.compute(decode.decode(IMG / "DSC_0001.JPG").rgb)
    p2 = phash.compute(decode.decode(IMG / "DSC_0002.JPG").rgb)
    p3 = phash.compute(decode.decode(IMG / "DSC_0030.JPG").rgb)
    print(f"  0001 ↔ 0002 hamming = {phash.hamming(p1.phash, p2.phash)}")
    print(f"  0001 ↔ 0030 hamming = {phash.hamming(p1.phash, p3.phash)}")


def test_decide_end_to_end() -> None:
    from blurdetector import pipeline

    banner("pipeline.analyze_one — end-to-end")
    for name in ["DSC_0038.JPG", "DSC_0009.JPG", "DSC_0001.JPG", "DSC_0015.JPG"]:
        r, ms = t(pipeline.analyze_one, IMG / name)
        v = r.verdict
        print(f"  {name}: verdict={v.verdict} stars={v.stars} score={v.score:.3f} "
              f"reasons={v.reasons}  [{ms:.0f} ms]")


def main() -> None:
    chosen = set(sys.argv[1:]) if len(sys.argv) > 1 else None
    steps = [
        ("decode", test_decode),
        ("exif", test_exif),
        ("sharpness", test_sharpness),
        ("subject", test_subject_and_subject_sharpness),
        ("eyes", test_eyes),
        ("exposure", test_exposure_noise_composition),
        ("phash", test_phash),
        ("pipeline", test_decide_end_to_end),
    ]
    for name, fn in steps:
        if chosen and name not in chosen:
            continue
        try:
            fn()
        except Exception as e:
            print(f"\n!! {name} failed: {type(e).__name__}: {e}")
            raise


if __name__ == "__main__":
    main()
