#!/usr/bin/env python3
"""
Speaker Name Detection Tool

This script detects speaker names from video conference screenshots or video files.
It automatically detects the speaker panel using computer vision and/or AI models,
then extracts text from that region using OCR to identify speaker names.

Key Features:
- Automatic speaker panel detection (no manual bounding box required)
- Support for both image files and video files
- Batch processing for efficient video analysis
- Multiple OCR engines: EasyOCR (default) and PaddleOCR
- Verbose diagnostics and debug crops to troubleshoot OCR behavior
- Outputs results in CSV format for video processing

Detection Methods:
- CV (Computer Vision): Fast edge detection method
- LLM (Large Language Model): AI-powered detection using Google Gemini
- CV+LLM: Tries CV first, falls back to LLM if needed (default)

Usage Examples:
    # Process a single image
    python get_speaker_names.py screenshot.png --ocr-model easyocr -v

    # Process a video with default 5-second intervals
    python get_speaker_names.py meeting.mp4 -v

    # Process video with custom interval and output file
    python get_speaker_names.py meeting.mp4 --interval 2.0 -o speakers.csv

    # Process only first 5 minutes with verbose output
    python get_speaker_names.py meeting.mp4 --duration 300 --verbose

    # Use PaddleOCR and auto bottom-ROI when skipping panel detection
    python get_speaker_names.py frame.png --no-crop --auto-roi --roi-bottom-ratio 0.35 --ocr-model paddleocr -v

Requirements:
- OpenCV (cv2)
- NumPy
- PIL (Pillow)
- EasyOCR (default OCR engine)
- FFmpeg (for video processing)
- Google Generative AI (optional, for LLM fallback)
- python-dotenv
- Optional OCR engine: PaddleOCR (paddleocr + paddlepaddle)

Note: This script imports detection functions from get_speaker_bbox.py
"""

import argparse
import os
import re
import csv
import subprocess
import tempfile
import numpy as np
import json
from typing import Tuple, Optional
from PIL import Image, ImageOps
import easyocr
# Optional PaddleOCR
try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None
import logging

# Import speaker bbox detection functions
from get_speaker_bbox import detect_speaker_bbox_cv, detect_speaker_bbox_llm


# Preprocess helper
def preprocess_image_for_ocr(img: Image.Image, upscale: float = 1.0, binarize: bool = False, verbose: bool = False) -> Tuple[Image.Image, dict]:
    """
    Preprocess image before OCR.
    - optional upscale (>=1.0)
    - optional binarization (Otsu on grayscale)
    Returns processed image and diagnostics dict.
    """
    info = {"original_size": img.size}
    out = img
    if upscale and upscale > 1.0:
        new_w = max(1, int(img.width * upscale))
        new_h = max(1, int(img.height * upscale))
        out = out.resize((new_w, new_h), resample=Image.LANCZOS)
        info["upscaled_size"] = out.size
    # Always grayscale before binarize to keep engines robust
    if binarize:
        gray = ImageOps.grayscale(out)
        # Simple global threshold using Otsu via numpy
        arr = np.array(gray)
        # Otsu threshold
        hist, _ = np.histogram(arr, bins=256, range=(0, 255))
        total = arr.size
        sumB = 0.0
        wB = 0.0
        maximum = 0.0
        sum1 = np.dot(np.arange(256), hist)
        threshold = 0
        for i in range(256):
            wB += hist[i]
            if wB == 0:
                continue
            wF = total - wB
            if wF == 0:
                break
            sumB += i * hist[i]
            mB = sumB / wB
            mF = (sum1 - sumB) / wF
            between = wB * wF * (mB - mF) ** 2
            if between > maximum:
                threshold = i
                maximum = between
        bin_img = (arr > threshold).astype(np.uint8) * 255
        out = Image.fromarray(bin_img)
        info["binarize_threshold"] = int(threshold)
        info["binarized"] = True
    if verbose:
        ow, oh = info["original_size"]
        print(f"[preprocess] original: {ow}x{oh} upscale={upscale if upscale else 1.0} binarize={binarize}")
        if "upscaled_size" in info:
            uw, uh = info["upscaled_size"]
            print(f"[preprocess] upscaled: {uw}x{uh}")
        if info.get("binarized"):
            print(f"[preprocess] binarized with threshold={info['binarize_threshold']}")
    return out, info


def get_speaker_bbox(image_path: str, method: str = "cv+llm", verbose: bool = False) -> dict:
    """
    Automatically detect speaker panel bounding box from an image.
    
    Args:
        image_path: Path to the image file
        method: Detection method ("cv", "llm", or "cv+llm")
        verbose: If True, print progress information
        
    Returns:
        Dictionary with normalized bounding box coordinates or None if not found
    """
    result = None
    
    if method in ("cv", "cv+llm"):
        try:
            result = detect_speaker_bbox_cv(image_path, debug=False)
            if verbose:
                print("Speaker panel detected using CV method")
        except Exception as e:
            if verbose:
                print(f"CV detection failed: {e}")
    
    if result is None and method in ("llm", "cv+llm"):
        try:
            result = detect_speaker_bbox_llm(image_path)
            if verbose:
                print("Speaker panel detected using LLM method")
        except Exception as e:
            if verbose:
                print(f"LLM detection failed: {e}")
    
    if result and result.get("found_speaker_panel") and result.get("bounding_box"):
        return result["bounding_box"]
    
    if verbose:
        print("No speaker panel found")
    return None


def get_video_duration(video_path: str) -> float:
    """
    Get the duration of a video file in seconds using ffprobe.
    
    Args:
        video_path: Path to the video file
        
    Returns:
        Duration in seconds, or None if error
    """
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"Error getting video duration: {e}")
        return None


def extract_frame_at_time(video_path: str, timestamp: float, output_path: str) -> bool:
    """
    Extract a single frame from a video at a specific timestamp.
    
    Args:
        video_path: Path to the video file
        timestamp: Time in seconds
        output_path: Path to save the extracted frame
        
    Returns:
        True if successful, False otherwise
    """
    try:
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-ss", str(timestamp),
            "-vframes", "1",
            output_path
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error extracting frame at {timestamp}s: {e}")
        return False


def extract_frames_batch(video_path: str, timestamps: list, temp_dir: str, frame_start_number: int = 0, verbose: bool = False) -> dict:
    """
    Extract multiple frames from a video at specified timestamps using FFmpeg.
    
    Args:
        video_path: Path to the video file
        timestamps: List of timestamps in seconds
        temp_dir: Directory to save extracted frames
        frame_start_number: Starting frame number for naming (for sequential numbering)
        verbose: If True, print progress information
        
    Returns:
        Dictionary mapping timestamp to frame path for successfully extracted frames
    """
    result = {}
    
    if not timestamps:
        return result
    
    if verbose:
        print(f"Extracting {len(timestamps)} frames in batch...")
    
    try:
        # Build FFmpeg command for batch extraction
        cmd = ["ffmpeg", "-y", "-i", video_path]
        
        # Add each timestamp as a separate output
        for i, timestamp in enumerate(timestamps):
            frame_number = frame_start_number + i
            frame_path = os.path.join(temp_dir, f"frame_{frame_number:04d}_{timestamp:.2f}s.png")
            cmd.extend([
                "-ss", str(timestamp),
                "-t", "0.04",  # Very short duration to get just one frame
                "-vframes", "1",
                frame_path
            ])
        
        # Execute FFmpeg command
        subprocess.run(cmd, capture_output=True, check=True)
        
        # Check which frames were successfully created
        for i, timestamp in enumerate(timestamps):
            frame_number = frame_start_number + i
            frame_path = os.path.join(temp_dir, f"frame_{frame_number:04d}_{timestamp:.2f}s.png")
            if os.path.exists(frame_path):
                result[timestamp] = frame_path
            else:
                if verbose:
                    print(f"Warning: Frame at {timestamp:.2f}s was not created")
        
        if verbose:
            print(f"Successfully extracted {len(result)}/{len(timestamps)} frames")
        
        return result
        
    except subprocess.CalledProcessError as e:
        if verbose:
            print(f"Batch extraction failed: {e}")
        # Fallback to individual frame extraction
        if verbose:
            print("Falling back to individual frame extraction...")
        
        for i, timestamp in enumerate(timestamps):
            frame_number = frame_start_number + i
            frame_path = os.path.join(temp_dir, f"frame_{frame_number:04d}_{timestamp:.2f}s.png")
            if extract_frame_at_time(video_path, timestamp, frame_path):
                result[timestamp] = frame_path
        
        return result


# New: helper to perform OCR with selected model and return (text, confidence) tuples
def perform_ocr(target_img: Image.Image, ocr_model: str, reader: easyocr.Reader = None, verbose: bool = False, *, upscale: Optional[float] = None, binarize: bool = False):
    """
    Perform OCR using the specified model.
    Returns a list of (text, confidence) tuples.
    """
    results = []
    # Preprocess image consistently for all engines if flags provided
    # If no upscale provided, default = 1.0
    default_upscale = 1.0
    eff_upscale = upscale if (isinstance(upscale, (int, float)) and upscale and upscale > 0) else default_upscale
    processed_img, _ = preprocess_image_for_ocr(target_img, upscale=eff_upscale, binarize=binarize, verbose=verbose)

    if ocr_model == "easyocr":
        if reader is None:
            reader = easyocr.Reader(['en'])
        target_array = np.array(processed_img)
        try:
            ocr_results = reader.readtext(target_array)
        except Exception as e:
            if verbose:
                print(f"EasyOCR failed: {e}")
            ocr_results = []
        for (_bbox, text, confidence) in ocr_results:
            if verbose:
                print(f"[easyocr] raw: text='{text}' conf={float(confidence):.2f}")
            results.append((text, float(confidence)))
        return results
    elif ocr_model == "paddleocr":
        if PaddleOCR is None:
            print("PaddleOCR requested but paddleocr is not installed. Install with 'pip install paddleocr' (and paddlepaddle).")
            return []
        # Lazy-initialize a global PaddleOCR instance for performance
        global _paddle_ocr_instance
        if '_paddle_ocr_instance' not in globals() or globals().get('_paddle_ocr_instance') is None:
            if verbose:
                print("Initializing PaddleOCR (en)...")
            # Configure logging for PaddleOCR
            # Suppress DEBUG logs unless verbose is True
            ppocr_logger = logging.getLogger('ppocr')
            paddle_logger = logging.getLogger('paddle')
            root_logger = logging.getLogger()
            if verbose:
                ppocr_logger.setLevel(logging.INFO)
                paddle_logger.setLevel(logging.INFO)
            else:
                ppocr_logger.setLevel(logging.WARNING)
                paddle_logger.setLevel(logging.ERROR)
                root_logger.setLevel(logging.WARNING)
                # Suppress Paddle internal logs (INFO/DEBUG)
                os.environ.setdefault('FLAGS_minloglevel', '2')  # 0=INFO, 1=WARNING, 2=ERROR
            try:
                # use_textline_orientation replaces deprecated use_angle_cls
                globals()['_paddle_ocr_instance'] = PaddleOCR(use_textline_orientation=True, lang='en', show_log=verbose)
            except Exception as e:
                print(f"Failed to initialize PaddleOCR: {e}")
                return []
        ocr = globals()['_paddle_ocr_instance']
        # Convert PIL image to numpy array RGB
        np_img = np.array(processed_img)
        try:
            ocr_result = ocr.ocr(np_img, cls=True)
        except Exception as e:
            if verbose:
                print(f"PaddleOCR failed: {e}")
            ocr_result = []
        # ocr_result format: list of [ [ (bbox, (text, confidence)), ... ] ]
        for page in ocr_result or []:
            for item in page or []:
                # item: [bbox, (text, conf)]
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    text = item[1][0]
                    conf = float(item[1][1])
                    if verbose:
                        print(f"[paddleocr] raw: text='{text}' conf={conf:.2f}")
                    results.append((text, conf))
        return results
    else:
        return []


def process_video(video_path: str, interval: float, output_csv: str, 
                 max_duration: float = None, batch_size: int = 20, verbose: bool = False, debug: bool = False, no_crop: bool = False,
                 ocr_model: str = "easyocr", *, min_ocr_conf: float = 0.5, ocr_upscale: Optional[float] = None, ocr_binarize: bool = False,
                 auto_roi: bool = False, roi_bottom_ratio: float = 0.32) -> bool:
    """
    Process a video file, extracting frames at intervals and detecting speaker names.
    
    Args:
        video_path: Path to the video file
        interval: Time interval in seconds between frame extractions
        output_csv: Path to output CSV file
        max_duration: Maximum duration in seconds to process (None = entire video)
        batch_size: Number of frames to extract in each batch
        verbose: If True, print progress information
        debug: If True, preserve temporary frame files for troubleshooting
        no_crop: If True, skip speaker panel detection and process entire images
        ocr_model: OCR engine to use for text detection ("easyocr" or "paddleocr")
        min_ocr_conf: Minimum OCR confidence to accept a candidate
        ocr_upscale: Pre-OCR upscale factor (overrides engine default)
        ocr_binarize: Apply binarization before OCR
        auto_roi: When --no-crop is used, crop bottom portion (ratio) before OCR
        roi_bottom_ratio: Fraction of image height to keep from bottom when auto_roi is enabled
        
    Returns:
        True if successful, False otherwise
    """
    if not os.path.exists(video_path):
        print(f"Error: Video file not found at '{video_path}'")
        return False
    
    # Get video duration
    duration = get_video_duration(video_path)
    if duration is None:
        return False
    
    # Use max_duration if specified and smaller than actual duration
    if max_duration is not None:
        duration = min(duration, max_duration)
        if verbose:
            print(f"Processing limited to {duration:.2f} seconds (--duration option)")
    
    if verbose:
        print(f"Video duration: {duration:.2f} seconds")
        print(f"Extracting frames every {interval} seconds...")
        print(f"OCR model: {ocr_model}")
        print(f"min_ocr_conf={min_ocr_conf} ocr_upscale={ocr_upscale if ocr_upscale else 1.0} ocr_binarize={ocr_binarize}")
        if no_crop and auto_roi:
            print(f"auto_roi bottom ratio: {roi_bottom_ratio}")
    
    # Initialize OCR reader once (reuse for all frames) if using EasyOCR
    reader = None
    if ocr_model == "easyocr":
        print("Initializing OCR reader...")
        reader = easyocr.Reader(['en'])
    
    # Calculate all timestamps that need to be processed
    all_timestamps = []
    current_time = 0.0
    while current_time < duration:
        all_timestamps.append(current_time)
        current_time += interval
    
    if verbose:
        print(f"Will process {len(all_timestamps)} frames in batches of {batch_size}")
    
    # Create temporary directory for extracted frames
    if debug:
        # Create a persistent temp directory for debugging (cropped regions only)
        mode_suffix = "full_images" if no_crop else "cropped_regions"
        debug_dir = f"debug_{mode_suffix}_{os.path.basename(video_path).split('.')[0]}"
        os.makedirs(debug_dir, exist_ok=True)
        if no_crop:
            print(f"Debug mode: Full images will be saved in '{debug_dir}' directory")
        else:
            print(f"Debug mode: Cropped speaker regions will be saved in '{debug_dir}' directory")
        # Still need a temp dir for the full frames during processing
        temp_dir_context = tempfile.TemporaryDirectory()
        temp_dir = temp_dir_context.name
    else:
        debug_dir = None
        temp_dir_context = tempfile.TemporaryDirectory()
        temp_dir = temp_dir_context.name
    
    try:
        results = []
        timestamps = []
        frame_counter = 0
        
        # Process frames in batches
        for batch_start in range(0, len(all_timestamps), batch_size):
            batch_end = min(batch_start + batch_size, len(all_timestamps))
            batch_timestamps = all_timestamps[batch_start:batch_end]
            
            if verbose:
                print(f"Processing batch {batch_start//batch_size + 1}/{(len(all_timestamps) + batch_size - 1)//batch_size} "
                      f"({len(batch_timestamps)} frames)...")
            
            # Extract frames for this batch
            extracted_frames = extract_frames_batch(video_path, batch_timestamps, temp_dir, 
                                                   frame_start_number=frame_counter, verbose=verbose)
            frame_counter += len(batch_timestamps)
            
            # Process each frame in the batch
            for timestamp in batch_timestamps:
                if verbose:
                    progress = (batch_start + (timestamp - batch_timestamps[0]) / interval) / len(all_timestamps) * 100
                    print(f"Processing frame at {timestamp:.2f}s ({progress:.1f}%)...")
                
                frame_path = extracted_frames.get(timestamp)
                
                if frame_path and os.path.exists(frame_path):
                    # Detect speaker name
                    name = detect_speaker_name_from_image(
                        frame_path,
                        reader=reader,
                        verbose=verbose,
                        debug_dir=debug_dir,
                        no_crop=no_crop,
                        ocr_model=ocr_model,
                        min_ocr_conf=min_ocr_conf,
                        ocr_upscale=ocr_upscale,
                        ocr_binarize=ocr_binarize,
                        auto_roi=auto_roi,
                        roi_bottom_ratio=roi_bottom_ratio,
                    )
                    
                    # Format timestamp as HH:MM:SS
                    hours = int(timestamp // 3600)
                    minutes = int((timestamp % 3600) // 60)
                    seconds = int(timestamp % 60)
                    timestamp_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    
                    results.append(name if name else "")
                    timestamps.append(timestamp_str)
                    
                    if verbose and name:
                        print(f"  -> Detected: {name}")
                else:
                    # Frame extraction failed for this timestamp
                    hours = int(timestamp // 3600)
                    minutes = int((timestamp % 3600) // 60)
                    seconds = int(timestamp % 60)
                    timestamp_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    
                    results.append("")
                    timestamps.append(timestamp_str)
                    if verbose:
                        print(f"  -> Failed to extract frame at {timestamp:.2f}s")
        
        # Write results to CSV
        try:
            with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['timestamp', 'speaker_name'])
                for ts, name in zip(timestamps, results):
                    writer.writerow([ts, name])
            
            print(f"\nResults saved to: {output_csv}")
            print(f"Processed {len(results)} frames")
            detected_count = sum(1 for name in results if name)
            print(f"Detected speaker names in {detected_count} frames")
            if debug:
                mode_desc = "full images" if no_crop else "cropped speaker regions"
                print(f"Debug {mode_desc} preserved in: {debug_dir}")
            return True
        except Exception as e:
            print(f"Error writing CSV file: {e}")
            return False
    
    finally:
        # Clean up temporary directory (always cleanup since we always use temp dir for full frames)
        if 'temp_dir_context' in locals():
            temp_dir_context.cleanup()


def detect_speaker_name_from_image(image_path: str, 
                                   reader: easyocr.Reader = None, 
                                   verbose: bool = True,
                                   debug_dir: str = None,
                                   no_crop: bool = False,
                                   ocr_model: str = "easyocr",
                                   *,
                                   min_ocr_conf: float = 0.5,
                                   ocr_upscale: Optional[float] = None,
                                   ocr_binarize: bool = False,
                                   auto_roi: bool = False,
                                   roi_bottom_ratio: float = 0.32) -> str:
    """
    Detects speaker name from an image file.
    Automatically detects speaker panel bounding box and processes that region.
    
    Args:
        image_path: Path to the image file
        reader: EasyOCR reader instance (if None, will create one)
        verbose: If True, print progress information
        debug_dir: Directory to save cropped speaker regions for debugging (if provided)
        no_crop: If True, skip speaker panel detection and process the entire image
        ocr_model: OCR engine to use for text detection ("easyocr" or "paddleocr")
        min_ocr_conf: Minimum OCR confidence threshold for candidate acceptance
        ocr_upscale: Pre-OCR upscale factor (overrides engine default)
        ocr_binarize: Apply binarization before OCR
        auto_roi: When --no-crop is used, crop bottom portion (ratio) before OCR
        roi_bottom_ratio: Fraction of image height to keep from bottom when auto_roi is enabled
        
    Returns:
        Detected speaker name or None if not found
    """
    if not os.path.exists(image_path):
        return None
    
    # Load image
    img = Image.open(image_path)
    width, height = img.size
    
    # Determine which image to process
    if no_crop:
        # Skip speaker panel detection and use the entire image (optionally apply bottom ROI)
        if auto_roi:
            roi_h = int(height * roi_bottom_ratio)
            top = max(0, height - roi_h)
            target_img = img.crop((0, top, width, height))
            region_name = f"full_image_auto_roi({roi_bottom_ratio:.2f})"
            if verbose:
                print("Skipping speaker panel detection (--no-crop). Using bottom-ROI before OCR.")
                print(f"Auto-ROI crop: (0,{top},{width},{height})")
                print(f"Crop dimensions (auto-ROI): {width}x{height - top}")
        else:
            target_img = img
            region_name = "full_image"
            if verbose:
                print("Skipping speaker panel detection, using entire image for OCR")
                print(f"Crop dimensions (full image): {width}x{height}")
        
        # Save cropped/full image if debug directory is provided
        if debug_dir:
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            suffix = "full_image" if not auto_roi else "auto_roi"
            full_image_path = os.path.join(debug_dir, f"{base_name}_{suffix}.png")
            target_img.save(full_image_path)
            if verbose:
                print(f"Saved {suffix.replace('_',' ')} to: {full_image_path}")
    else:
        # Automatically detect speaker panel bounding box
        bbox = get_speaker_bbox(image_path, method="cv+llm", verbose=verbose)
        
        if bbox:
            # Convert normalized coordinates to pixel coordinates
            crop_left = int(bbox['x'] * width)
            crop_top = int(bbox['y'] * height)
            crop_right = int((bbox['x'] + bbox['width']) * width)
            crop_bottom = int((bbox['y'] + bbox['height']) * height)
            
            # Ensure coordinates are within image bounds
            crop_left = max(0, min(crop_left, width))
            crop_top = max(0, min(crop_top, height))
            crop_right = max(crop_left, min(crop_right, width))
            crop_bottom = max(crop_top, min(crop_bottom, height))
            
            target_img = img.crop((crop_left, crop_top, crop_right, crop_bottom))
            region_name = "detected_bbox"
            if verbose:
                print(f"Using detected bounding box: ({crop_left}, {crop_top}, {crop_right}, {crop_bottom})")
                print(f"Crop dimensions: {crop_right - crop_left}x{crop_bottom - crop_top}")
            
            # Save cropped region if debug directory is provided
            if debug_dir:
                base_name = os.path.splitext(os.path.basename(image_path))[0]
                cropped_path = os.path.join(debug_dir, f"{base_name}_cropped_speaker_region.png")
                target_img.save(cropped_path)
                if verbose:
                    print(f"Saved cropped speaker region to: {cropped_path}")
        else:
            # Fall back to full image if detection failed
            target_img = img
            region_name = "full"
            if verbose:
                print("Speaker panel detection failed, using full image")
                print(f"Crop dimensions (full image fallback): {width}x{height}")
            
            # Save full image if debug directory is provided and no bbox was found
            if debug_dir:
                base_name = os.path.splitext(os.path.basename(image_path))[0]
                fallback_path = os.path.join(debug_dir, f"{base_name}_full_image_fallback.png")
                target_img.save(fallback_path)
                if verbose:
                    print(f"Saved full image fallback to: {fallback_path}")
    
    # Initialize OCR if needed and perform OCR via helper
    if verbose:
        print(f"Performing OCR on {region_name} region with model '{ocr_model}'...")
        # Report target (pre-OCR) image size
        tw, th = target_img.size
        print(f"Target OCR image size: {tw}x{th}")
    texts = perform_ocr(target_img, ocr_model=ocr_model, reader=reader, verbose=verbose, upscale=ocr_upscale, binarize=ocr_binarize)
    
    # Apply existing filtering and scoring logic but using texts list
    all_detected_names = []
    if verbose:
        print(f"Total OCR text candidates: {len(texts)} (min_conf={min_ocr_conf})")
    for (text, confidence) in texts:
        if confidence >= float(min_ocr_conf):
            cleaned = re.sub(r'[^\w\s]', '', text).strip()
            if len(cleaned) > 2:
                words = cleaned.split()
                is_name_like = (len(words) >= 2) or (len(words) == 1 and any(c.isupper() for c in cleaned))
                if is_name_like:
                    all_detected_names.append((cleaned, confidence, region_name))
                    if verbose:
                        print(f"  -> Accepted candidate: '{cleaned}' (confidence: {confidence:.2f})")
                else:
                    if verbose:
                        print(f"  -> Rejected (not name-like): '{cleaned}' conf={confidence:.2f}")
            else:
                if verbose:
                    print(f"  -> Rejected (too short): '{text}' conf={confidence:.2f}")
        else:
            if verbose:
                print(f"  -> Rejected (low confidence): '{text}' conf={confidence:.2f}")
    
    # Return best result (prioritize multi-word names that look like person names)
    if all_detected_names:
        scored_names = []
        for name, confidence, region in all_detected_names:
            words = name.split()
            score = confidence
            # Favor human-style names (multi-word, capitalized)
            if len(words) >= 2:
                score += 0.3
                # Extra bonus if both words start with capital (proper name)
                if all(word and word[0].isupper() for word in words):
                    score += 0.2
            scored_names.append((name, score, confidence, region))
        
        scored_names.sort(key=lambda x: x[1], reverse=True)
        best_match = scored_names[0]
        if verbose:
            print(f"Best match from {best_match[3]} region: '{best_match[0]}' (score: {best_match[1]:.2f}, confidence: {best_match[2]:.2f})")
        return best_match[0]
    
    if verbose:
        print("No name-like text found after filtering.")
    return None


def main():
    """
    Main function to handle command-line arguments for speaker name detection.
    Supports both image files and video files.
    """
    parser = argparse.ArgumentParser(
        description="Detect speaker name from a Google Meet frame or video recording."
    )
    parser.add_argument("input_file", help="Path to the input file (image: .png, .jpg) or video (.mp4).")
    parser.add_argument("--interval", type=float, default=5.0,
                       help="Time interval in seconds between frame extractions (for video files only, default: 5.0).")
    parser.add_argument("--duration", type=float,
                       help="Maximum duration in seconds to process (for video files only). If not specified, processes the entire video.")
    parser.add_argument("-o", "--output", help="Output CSV file path (for video files only). If not provided, will be input filename with .csv extension.")
    parser.add_argument("--batch-size", type=int, default=20,
                       help="Number of frames to extract in each batch (default: 20). Higher values may be faster but use more memory.")
    parser.add_argument("-v", "--verbose", action="store_true",
                       help="Print verbose progress information.")
    parser.add_argument("--debug", action="store_true",
                       help="Keep temporary frame images after processing for troubleshooting.")
    parser.add_argument("--no-crop", action="store_true",
                       help="Skip speaker panel detection and process the entire image with OCR.")
    # New: allow choosing OCR model
    parser.add_argument("--ocr-model", choices=["easyocr", "paddleocr"], default="easyocr",
                       help="OCR engine to use for text detection (default: easyocr).")
    # New: OCR tuning and diagnostics
    parser.add_argument("--min-ocr-conf", type=float, default=0.5,
                       help="Minimum OCR confidence threshold to accept text as a name candidate (default: 0.5).")
    parser.add_argument("--ocr-upscale", type=float,
                       help="Pre-OCR upscale factor. If not set, uses a sensible default (1.0).")
    parser.add_argument("--ocr-binarize", action="store_true",
                       help="Apply binarization before OCR (can help on low-contrast UI text).")
    parser.add_argument("--auto-roi", action="store_true",
                       help="When used with --no-crop, automatically crop the bottom portion of the frame before OCR to reduce UI noise.")
    parser.add_argument("--roi-bottom-ratio", type=float, default=0.32,
                       help="Fraction of image height to keep from bottom when --auto-roi is enabled (default: 0.32).")
    args = parser.parse_args()
    
    # Check if input is a video file
    video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
    is_video = any(args.input_file.lower().endswith(ext) for ext in video_extensions)
    
    if is_video:
        # Process video file
        output_csv = args.output
        if not output_csv:
            # Generate output filename from input
            base_name = os.path.splitext(args.input_file)[0]
            output_csv = f"{base_name}_speakers.csv"
        
        success = process_video(
            args.input_file,
            args.interval,
            output_csv,
            max_duration=args.duration,
            batch_size=args.batch_size,
            verbose=args.verbose,
            debug=args.debug,
            no_crop=args.no_crop,
            ocr_model=args.ocr_model,
            min_ocr_conf=args.min_ocr_conf,
            ocr_upscale=args.ocr_upscale,
            ocr_binarize=args.ocr_binarize,
            auto_roi=args.auto_roi,
            roi_bottom_ratio=args.roi_bottom_ratio,
        )
        if not success:
            exit(1)
    else:
        # Process image file (original functionality)
        debug_dir = None
        if args.debug:
            # Create debug directory for single image processing
            base_name = os.path.splitext(os.path.basename(args.input_file))[0]
            mode_suffix = "full_image" if args.no_crop else "cropped_region"
            debug_dir = f"debug_{mode_suffix}_{base_name}"
            os.makedirs(debug_dir, exist_ok=True)
            if args.no_crop:
                print(f"Debug mode: Full image will be saved in '{debug_dir}' directory")
            else:
                print(f"Debug mode: Cropped speaker region will be saved in '{debug_dir}' directory")
        
        name = detect_speaker_name_from_image(
            args.input_file,
            verbose=True,
            debug_dir=debug_dir,
            no_crop=args.no_crop,
            ocr_model=args.ocr_model,
            min_ocr_conf=args.min_ocr_conf,
            ocr_upscale=args.ocr_upscale,
            ocr_binarize=args.ocr_binarize,
            auto_roi=args.auto_roi,
            roi_bottom_ratio=args.roi_bottom_ratio,
        )
        
        if name:
            print(f"Detected speaker name: {name}")
        else:
            print("No speaker name detected.")


if __name__ == "__main__":
    main()

