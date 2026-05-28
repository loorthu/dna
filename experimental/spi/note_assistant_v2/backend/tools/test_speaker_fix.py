#!/usr/bin/env python3
"""
Smoke test for the speaker-name OCR fixes:
  1. _is_ocr_garbage() structural filter catches all known-bad names
  2. Left-bbox expansion (_BBOX_LEFT_PAD_FRAC) is applied correctly
  3. End-to-end OCR on real frames

Usage:
    python test_speaker_fix.py [frame1.png frame2.png ...]

Defaults to /tmp/frame_1min.png if no args given.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import easyocr
import torch
from PIL import Image
from get_onscreen_text import (
    detect_speaker_name_from_image,
    _is_ocr_garbage,
    _MIN_OCR_CONFIDENCE,
    _BBOX_LEFT_PAD_FRAC,
)

# Names that MUST be flagged as garbage by the structural filter
MUST_REJECT = [
    "C ITUM HAU", "CGuD ReT", "CL GUDT AiLtM", "CL IUDT Ru", "CLE GTUD Reut",
    "DTNvd Kue", "ELE Gnut Faln", "ELIVDT Fur", "ELL EULT Fitn", "ELLTLA ctoRU",
    "Fean LoFD ARACAT", "FlenWm Ar", "GUTD hau", "JI LoD40", "KLLFNn  Eun",
    "LFNA enatnt", "TLTL FNn Eaclaent", "TLo DeRcT", "Ta LOTDeecu",
    "WuTvo Gou", "1 Vassallo", "t4208Hans Heymans",
]

# These look superficially title-case; they slip past the pattern filter but
# will be rejected by the _MIN_OCR_CONFIDENCE threshold at runtime.
CONFIDENCE_GATED = ["Teaka Hondma Cut", "ULee"]

# Truncated names (bbox left-clipping) — must NOT be filtered out, since
# the bbox expansion fix should restore the full name.
MUST_PASS = [
    "helle Ramirez",          # → Michelle Ramirez (after bbox fix)
    "hony Syracuse",          # → Anthony Syracuse
    "id Cortes Altamirano",   # → David Cortes Altamirano
    "istyn Howard",           # → Kristyn Howard
    "my Hoey",                # → Amy Hoey
    "re Norris",              # → Andre/Dre Norris
    "s Simic",
]


def validate_filter():
    print("=" * 60)
    print("1. _is_ocr_garbage() unit-test")
    print("=" * 60)
    fail = False

    for name in MUST_REJECT:
        caught = _is_ocr_garbage(name)
        tag = "✓ GARBAGE" if caught else "✗ MISSED"
        if not caught:
            fail = True
        print(f"  {tag}: {repr(name)}")

    print()
    print(f"  Confidence-gated (conf<{_MIN_OCR_CONFIDENCE} rejects these at runtime):")
    for name in CONFIDENCE_GATED:
        caught = _is_ocr_garbage(name)
        tag = "~ confidence-only" if not caught else "✓ GARBAGE"
        print(f"  {tag}: {repr(name)}")

    print()
    print("  Must-pass (truncated names, not garbage):")
    for name in MUST_PASS:
        caught = _is_ocr_garbage(name)
        tag = "✓ PASS" if not caught else "✗ FALSE-POSITIVE"
        if caught:
            fail = True
        print(f"  {tag}: {repr(name)}")

    print()
    if fail:
        print("FAILURES DETECTED — review _is_ocr_garbage()")
    else:
        print("All structural filter checks passed.")
    print()


def validate_left_pad(image_path: str):
    """Verify the left-pad expansion shifts crop_left leftward vs raw bbox x."""
    from get_speaker_bbox import detect_speaker_bbox_cv
    result = detect_speaker_bbox_cv(image_path, debug=False)
    if not (result and result.get("found_speaker_panel")):
        print(f"  Cannot detect speaker panel in {image_path}, skipping pad test.")
        return
    bbox = result["bounding_box"]
    img = Image.open(image_path)
    width = img.size[0]
    raw_left = int(bbox['x'] * width)
    left_pad = int(width * _BBOX_LEFT_PAD_FRAC)
    padded_left = max(0, raw_left - left_pad)
    print("=" * 60)
    print(f"2. Left-pad expansion check on {os.path.basename(image_path)}")
    print("=" * 60)
    print(f"  Image width     : {width}px")
    print(f"  _BBOX_LEFT_PAD_FRAC: {_BBOX_LEFT_PAD_FRAC} ({left_pad}px)")
    print(f"  Raw crop_left   : {raw_left}px")
    print(f"  Padded crop_left: {padded_left}px  (expanded {raw_left - padded_left}px leftward)")
    print(f"  → verbose output will show crop_left={padded_left}")
    print()


def test_frame(path: str, reader: easyocr.Reader):
    print("=" * 60)
    print(f"3. OCR on {os.path.basename(path)}")
    print("=" * 60)
    result = detect_speaker_name_from_image(
        path,
        reader=reader,
        verbose=True,
        debug_dir=None,
        no_crop=False,
        fixed_bbox=None,
    )
    print(f"\n>>> Final detected speaker name: {repr(result)}")
    print()


def main():
    frames = sys.argv[1:] or ["/tmp/frame_1min.png"]
    missing = [f for f in frames if not os.path.exists(f)]
    if missing:
        print(f"Missing frames: {missing}")
        sys.exit(1)

    validate_filter()

    for frame in frames:
        validate_left_pad(frame)

    use_gpu = torch.cuda.is_available()
    print(f"Initialising EasyOCR (GPU={use_gpu})...")
    reader = easyocr.Reader(['en'], gpu=use_gpu, verbose=False)
    print()

    for frame in frames:
        test_frame(frame, reader)


if __name__ == "__main__":
    main()
