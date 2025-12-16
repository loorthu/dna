#!/usr/bin/env python3
"""
Speaker Panel Detection Tool

This script detects and extracts speaker panels from video conference screenshots.
It's designed to work with meeting recordings where the layout typically consists of:
- A shared screen on the LEFT side
- A speaker panel on the RIGHT side (containing video and name/room label)

The tool provides two detection methods:

1. Computer Vision (CV) Method:
   - Uses edge detection to find the vertical split between shared screen and speaker panel
   - Applies vertical trimming to remove black bars
   - Fast and works well with consistent layouts

2. Large Language Model (LLM) Method:
   - Uses Google's Gemini AI to visually analyze the screenshot
   - More intelligent but requires API key and internet connection
   - Better at handling unusual layouts or edge cases

Features:
- Returns normalized bounding box coordinates (0.0-1.0 range)
- Optional image cropping and saving
- Debug mode for troubleshooting detection issues
- Fallback support (try CV first, then LLM if needed)

Usage Examples:
    # Basic CV detection
    python get_speaker_bbox.py screenshot.png

    # Use LLM method with cropped output
    python get_speaker_bbox.py screenshot.png --method llm --save-image

    # Try CV first, fallback to LLM if needed
    python get_speaker_bbox.py screenshot.png --method cv+llm --debug

Requirements:
- OpenCV (cv2)
- NumPy
- PIL (Pillow)
- Google Generative AI (for LLM method)
- python-dotenv
- GEMINI_API_KEY environment variable (for LLM method)

Output Format:
JSON with bounding box coordinates, confidence score, and metadata.
"""

import os
import sys
import json
import argparse
import base64
import logging

import cv2
import numpy as np
from PIL import Image
from dotenv import load_dotenv
import google.generativeai as genai

logging.getLogger("grpc").setLevel(logging.ERROR)

# ---------------------------
# CONFIG
# ---------------------------
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")

# ---------------------------
# VERTICAL TRIM HELPER
# ---------------------------

def trim_vertical_black_bars(panel_img):
    """
    Trim top/bottom black bars from a right-side panel image.
    Keeps the largest contiguous vertical band with wide content.
    """
    gray = cv2.cvtColor(panel_img, cv2.COLOR_BGR2GRAY)

    # Fraction of non-black pixels per row
    row_activity = np.mean(gray > 25, axis=1)

    # Require wide horizontal coverage (filters stray shared-screen text)
    active = row_activity > 0.20

    if not np.any(active):
        return panel_img, 0, panel_img.shape[0]

    idx = np.where(active)[0]
    start, end = idx[0], idx[-1]

    # Small safety padding
    pad = int(0.03 * (end - start))
    start = max(0, start - pad)
    end = min(panel_img.shape[0], end + pad)

    return panel_img[start:end, :], start, end

# ---------------------------
# CV DETECTION (VERTICAL SPLIT + TRIM)
# ---------------------------

def detect_speaker_bbox_cv(image_path, debug=False):
    """
    Detect speaker panel by:
      1. Finding vertical split between shared screen (left)
         and speaker panel (right)
      2. Cropping full height from split to right edge
      3. Trimming top/bottom black bars
      4. Returning NORMALIZED bounding box
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError("Could not read image")

    H, W = img.shape[:2]

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)

    # Edge density per column
    col_density = np.mean(edges > 0, axis=0)

    # Smooth signal
    kernel = np.ones(25) / 25
    col_density = np.convolve(col_density, kernel, mode="same")

    # Search in right half
    search_start = int(0.5 * W)
    region = col_density[search_start:]

    # Strongest vertical transition
    gradient = np.abs(np.gradient(region))
    rel_x = int(np.argmax(gradient))
    split_x = search_start + rel_x

    if W - split_x < 0.1 * W:
        raise ValueError("Detected speaker panel too narrow")

    # Crop horizontally
    panel = img[:, split_x:W]

    # Trim vertical black bars
    panel_trimmed, y0, y1 = trim_vertical_black_bars(panel)

    if debug:
        dbg = img.copy()
        cv2.line(dbg, (split_x, 0), (split_x, H), (0, 0, 255), 2)
        cv2.imwrite("debug_split.png", dbg)
        cv2.imwrite("debug_panel_raw.png", panel)
        cv2.imwrite("debug_panel_trimmed.png", panel_trimmed)

    # Absolute bbox
    abs_x = split_x
    abs_y = y0
    abs_w = W - split_x
    abs_h = y1 - y0

    # Normalized bbox
    bbox_norm = {
        "x": abs_x / W,
        "y": abs_y / H,
        "width": abs_w / W,
        "height": abs_h / H,
    }

    return {
        "found_speaker_panel": True,
        "bounding_box": bbox_norm,
        "confidence": 0.99,
        "method": "cv",
        "image_width": W,
        "image_height": H,
    }

# ---------------------------
# LLM DETECTION (IMPROVED PROMPT)
# ---------------------------

def load_image_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


VL_PROMPT = """
You are performing visual localization on a video-conference screenshot.

Layout assumptions (very important):
- The shared screen occupies the LEFT portion of the image.
- The speaker panel occupies the RIGHT portion of the image.
- The speaker panel includes:
  - the speaker video
  - a visible text label (person name or room name),
    e.g. "TCSOB-3102-SB"
- The label text MUST be included in the bounding box.

Task:
Return the bounding box of the speaker panel.

Requirements:
- Coordinates must be pixel values relative to the original image.
- (0,0) is the top-left corner.
- x increases to the right, y increases downward.
- Prefer a box that includes the ENTIRE speaker panel
  rather than a tight crop of the face.
- Do NOT include shared-screen content on the left.
- Do NOT guess. If uncertain, return found_speaker_panel=false.

Return ONLY JSON in the following format:

{
  "found_speaker_panel": true | false,
  "bounding_box": {
    "x": <integer>,
    "y": <integer>,
    "width": <integer>,
    "height": <integer>
  },
  "confidence": <0.0-1.0>
}
"""


def detect_speaker_bbox_llm(image_path):
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    genai.configure(api_key=API_KEY)

    with Image.open(image_path) as img:
        W, H = img.width, img.height

    image_b64 = load_image_base64(image_path)
    model = genai.GenerativeModel("gemini-2.5-pro")

    response = model.generate_content(
        contents=[
            {
                "role": "user",
                "parts": [
                    {"text": VL_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": image_b64,
                        }
                    },
                ],
            }
        ]
    )

    data = json.loads(response.text)

    if not data.get("found_speaker_panel"):
        return data

    bbox = data["bounding_box"]

    # Normalize bbox
    bbox_norm = {
        "x": bbox["x"] / W,
        "y": bbox["y"] / H,
        "width": bbox["width"] / W,
        "height": bbox["height"] / H,
    }

    return {
        "found_speaker_panel": True,
        "bounding_box": bbox_norm,
        "confidence": data.get("confidence", 0.0),
        "method": "llm",
        "image_width": W,
        "image_height": H,
    }

# ---------------------------
# CROP HELPER
# ---------------------------

def crop_and_save(image_path, bbox_norm, image_width, image_height, output_path):
    x = int(bbox_norm["x"] * image_width)
    y = int(bbox_norm["y"] * image_height)
    w = int(bbox_norm["width"] * image_width)
    h = int(bbox_norm["height"] * image_height)

    with Image.open(image_path) as img:
        crop = img.crop((x, y, x + w, y + h))
        crop.save(output_path)

# ---------------------------
# MAIN
# ---------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Detect speaker panel in screenshots"
    )
    parser.add_argument("input_path", help="Input PNG image")
    parser.add_argument("--save-image", action="store_true")
    parser.add_argument(
        "--method",
        choices=["cv", "llm", "cv+llm"],
        default="cv",
        help="Detection method (default: cv)",
    )
    parser.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    image_path = args.input_path
    result = None

    if args.method in ("cv", "cv+llm"):
        try:
            result = detect_speaker_bbox_cv(image_path, debug=args.debug)
            print("Speaker panel detected using CV", file=sys.stderr)
        except Exception as e:
            print(f"CV detection failed: {e}", file=sys.stderr)

    if result is None and args.method in ("llm", "cv+llm"):
        try:
            result = detect_speaker_bbox_llm(image_path)
            print("Speaker panel detected using LLM", file=sys.stderr)
        except Exception as e:
            print(f"LLM detection failed: {e}", file=sys.stderr)
            sys.exit(1)

    if not result or not result.get("found_speaker_panel"):
        print("No speaker panel found", file=sys.stderr)
        sys.exit(1)

    if args.save_image and "bounding_box" in result:
        out = os.path.splitext(image_path)[0] + "_speaker_crop.png"
        crop_and_save(
            image_path,
            result["bounding_box"],
            result["image_width"],
            result["image_height"],
            out,
        )
        result["cropped_image_path"] = out

    result["input_file"] = image_path
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
