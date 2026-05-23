"""Compare IQA scoring and display final pipeline decisions (stars, verdict, combined score)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

# Setup environment variables for model paths
MODEL_DIR = Path("/Users/oindrila/Projects/macos-computer-vision-models/models")
os.environ["SNAPGRADE_TOPIQ_MODEL"] = str(MODEL_DIR / "topiq.mlpackage")
os.environ["SNAPGRADE_HYPERIQA_MODEL"] = str(MODEL_DIR / "hyperiqa.mlpackage")
os.environ["SNAPGRADE_NIMA_MODEL"] = str(MODEL_DIR / "nima.mlpackage")

from snapgrade import decode, pipeline, decide


def main():
    images_dir = Path("/Users/oindrila/Projects/BlurDetector/Images")
    
    # Gather images (up to 5 from each subdirectory)
    subdirs = [d for d in images_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
    image_paths: list[tuple[str, Path]] = []
    
    for d in sorted(subdirs):
        files = [f for f in d.iterdir() if f.is_file() and decode.is_supported(f)]
        # Pick first 5 images from each subdirectory to get a representative mix
        for f in sorted(files)[:5]:
            image_paths.append((d.name, f))
            
    print(f"Found {len(image_paths)} images to test.")
    
    # Header of markdown table
    rows = [
        "| Category | Image Name | TopIQ (Raw) | TopIQ (Normalized) | Combined Quality | Stars | Verdict |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |"
    ]
    
    for cat, path in image_paths:
        try:
            # Run the complete analysis pipeline
            res = pipeline.analyze_one(path)
            
            s_topiq = res.metrics.get("aesthetic_score")
            s_source = res.metrics.get("aesthetic_source")
            
            if s_topiq is not None and s_source == "topiq":
                s_norm = max(0.0, min(1.0, (s_topiq - 0.35) / 0.40))
            else:
                s_norm = 0.0
                
            topiq_raw_str = f"{s_topiq:.4f}" if s_topiq is not None else "N/A"
            topiq_norm_str = f"{s_norm:.4f}" if s_topiq is not None else "N/A"
            comb_score_str = f"{res.verdict.score:.4f}"
            stars_str = f"{'★' * res.verdict.stars}{'☆' * (5 - res.verdict.stars)}"
            verdict_str = res.verdict.verdict.upper()
            
            rows.append(f"| {cat} | {path.name} | {topiq_raw_str} | {topiq_norm_str} | {comb_score_str} | {stars_str} | {verdict_str} |")
            print(f"Processed: {cat}/{path.name} -> Raw: {topiq_raw_str}, Norm: {topiq_norm_str}, Quality: {comb_score_str}, Stars: {res.verdict.stars}, Verdict: {verdict_str}")
        except Exception as e:
            print(f"Failed to process {path.name}: {e}")
            
    print("\n--- NEW SYSTEM DECISION & RATING TABLE ---")
    print("\n".join(rows))
    print("------------------------------------------")


if __name__ == "__main__":
    main()
