#!/usr/bin/env python3
"""
Speaker Bounding Box Detection Tool

This script detects speaker panels in Google Meet recordings and extracts them.
Supports both image files (PNG, JPG) and MP4 video files.

Usage:
    python3 get_speaker_bbox.py [--save-image] <image_file.png>
    python3 get_speaker_bbox.py [--save-image] <video_file.mp4>

For video files (.mp4), the script will:
1. Extract the middle frame from the video (in memory)
2. Process that frame to detect the speaker panel
3. Optionally save cropped speaker panel if --save-image is specified

For image files, it will:
1. Process the image directly to detect the speaker panel
2. Optionally save cropped speaker panel if --save-image is specified

Output:
- JSON results to stdout
- Status messages to stderr
- Cropped speaker panel (only if --save-image): <image_name>_speaker_crop.png

Options:
    --save-image    Save the cropped speaker panel to disk
"""
import os
import sys
import warnings
import argparse

import google.generativeai as genai

import base64
import logging
from dotenv import load_dotenv
from PIL import Image
import cv2

logging.getLogger("grpc").setLevel(logging.ERROR)

import sys

# ---------------------------
# CONFIGURATION
# ---------------------------
load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not set in environment/.env")

genai.configure(api_key=API_KEY)

# ---------------------------
# HELPER: Extract middle frame from video
# ---------------------------
def extract_middle_frame(video_path):
    """
    Extract the middle frame from an MP4 video file to a temporary file.
    
    Args:
        video_path (str): Path to the video file
    
    Returns:
        str: Path to the temporary frame image
    """
    import tempfile
    
    # Create a temporary file for the frame
    temp_fd, temp_path = tempfile.mkstemp(suffix='.png', prefix='frame_')
    os.close(temp_fd)  # Close the file descriptor, we just need the path
    
    # Open video file
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        os.unlink(temp_path)  # Clean up temp file
        raise ValueError(f"Could not open video file: {video_path}")
    
    # Get total number of frames
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames == 0:
        cap.release()
        os.unlink(temp_path)  # Clean up temp file
        raise ValueError(f"No frames found in video: {video_path}")
    
    # Calculate middle frame position
    middle_frame = total_frames // 2
    
    # Set frame position to middle
    cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame)
    
    # Read the frame
    ret, frame = cap.read()
    cap.release()
    
    if not ret:
        os.unlink(temp_path)  # Clean up temp file
        raise ValueError(f"Could not read frame {middle_frame} from video: {video_path}")
    
    # Save frame as PNG
    success = cv2.imwrite(temp_path, frame)
    if not success:
        os.unlink(temp_path)  # Clean up temp file
        raise ValueError(f"Could not save frame to: {temp_path}")
    
    return temp_path


# ---------------------------
# HELPER: Load image as base64
# ---------------------------
def load_image_base64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------
# PROMPT: Structured extraction
# ---------------------------
VL_PROMPT = """
You are an image-analysis assistant. The input is a single video frame from a Google
Meet recording. Someone is typically sharing their screen (large main content area),
and on the right side there is an active speaker panel showing the speaker’s face and
their name as a text overlay near the bottom of the video tile.

Your task is to identify the bounding box of the active speaker panel in the image. Make sure 
that the speaker's name label is included in the bounding box.

Requirements:
1. Return ONLY structured JSON.
2. The JSON fields must be:

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

3. Coordinates must be pixel values relative to the original image.
4. If you cannot confidently locate the panel, return:

{
  "found_speaker_panel": false,
  "bounding_box": null,
  "confidence": 0.0
}

5. The bounding box should tightly enclose the speaker video tile including the name label.

Return ONLY the JSON object.
"""

# ---------------------------
# RUN REQUEST
# ---------------------------
def query_gemini_for_speaker_bbox(image_path):
    image_b64 = load_image_base64(image_path)

    # Gemini expects inline base64 as inline_data with mime_type and data
    image_part = {
        "inline_data": {
            "mime_type": "image/png",
            "data": image_b64,
        }
    }

    model = genai.GenerativeModel("gemini-2.5-pro")

    generation_config = {
        "response_mime_type": "application/json",
        "response_schema": {
            "type": "object",
            "properties": {
                "found_speaker_panel": {"type": "boolean"},
                "bounding_box": {
                    "type": "object",
                    "nullable": True,
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"}
                    },
                    "required": ["x", "y", "width", "height"]
                },
                "confidence": {"type": "number"}
            },
            "required": ["found_speaker_panel", "bounding_box", "confidence"]
        }
    }

    response = model.generate_content(
        contents=[
            {
                "role": "user",
                "parts": [
                    {"text": VL_PROMPT},
                    image_part,
                ],
            }
        ],
        generation_config=generation_config,
    )

    # Parse JSON and return structured dict
    import json as _json
    return _json.loads(response.text)


# ---------------------------
# HELPER: Crop and save speaker image
# ---------------------------
def crop_and_save_speaker(image_path, bbox, output_path=None):
    """
    Crop the speaker panel from the original image and save it.
    
    Args:
        image_path (str): Path to the original image
        bbox (dict): Bounding box with keys 'x', 'y', 'width', 'height'
        output_path (str): Optional output path. If None, generates based on input path
    
    Returns:
        str: Path to the saved cropped image
    """
    if output_path is None:
        # Generate output path based on input path
        base_name = os.path.splitext(image_path)[0]
        ext = os.path.splitext(image_path)[1]
        output_path = f"{base_name}_speaker_crop{ext}"
    
    # Open the original image
    with Image.open(image_path) as img:
        # Calculate crop coordinates
        left = bbox['x']
        top = bbox['y']
        right = left + bbox['width']
        bottom = top + bbox['height']
        
        # Ensure coordinates are within image bounds
        left = max(0, left)
        top = max(0, top)
        right = min(img.width, right)
        bottom = min(img.height, bottom)
        
        # Crop the image
        cropped_img = img.crop((left, top, right, bottom))
        
        # Save the cropped image
        cropped_img.save(output_path)
        
    return output_path


# ---------------------------
# MAIN
# ---------------------------
if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Detect speaker panels in Google Meet recordings')
    parser.add_argument('input_path', nargs='?', default='frame.png', 
                       help='Path to image file or MP4 video file')
    parser.add_argument('--save-image', action='store_true', 
                       help='Save the cropped speaker panel to disk')
    
    args = parser.parse_args()
    input_path = args.input_path
    save_image = args.save_image
    
    temp_frame_path = None  # Track temporary frame file for cleanup
    
    try:
        # Check if input is a video file
        if input_path.lower().endswith('.mp4'):
            try:
                # Extract middle frame from video to temporary file
                temp_frame_path = extract_middle_frame(input_path)
                image_path = temp_frame_path
            except Exception as e:
                print(f"Error extracting frame from video: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            # Input is already an image file
            image_path = input_path
        
        # Process the image with Gemini
        result = query_gemini_for_speaker_bbox(image_path)
        
        # If speaker panel was found and --save-image flag is set, crop and save the image
        if result.get("found_speaker_panel") and result.get("bounding_box") and save_image:
            try:
                # For videos, use the original video name for the cropped output
                if input_path.lower().endswith('.mp4'):
                    base_name = os.path.splitext(input_path)[0]
                    output_path = f"{base_name}_speaker_crop.png"
                else:
                    output_path = None  # Let the function generate the path
                
                cropped_path = crop_and_save_speaker(image_path, result["bounding_box"], output_path)
                result["cropped_image_path"] = cropped_path
                print(f"Speaker panel cropped and saved to: {cropped_path}", file=sys.stderr)
            except Exception as e:
                print(f"Error cropping image: {e}", file=sys.stderr)
                result["crop_error"] = str(e)
        elif result.get("found_speaker_panel") and result.get("bounding_box") and not save_image:
            print("Speaker panel found but not saving image (use --save-image to save)", file=sys.stderr)
        
        # Add metadata about the processing
        result["input_file"] = input_path
        if not input_path.lower().endswith('.mp4'):
            result["processed_image"] = image_path
        
        # Print JSON to stdout for redirection
        import json
        print(json.dumps(result, indent=2))
        
    finally:
        # Clean up temporary frame file if it was created
        if temp_frame_path and os.path.exists(temp_frame_path):
            try:
                os.unlink(temp_frame_path)
            except:
                pass  # Ignore cleanup errors
