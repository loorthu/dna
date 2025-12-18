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
- OCR engine: EasyOCR (default)
- Verbose diagnostics and debug crops to troubleshoot OCR behavior
- Outputs results in CSV format for video processing

Detection Methods:
- CV (Computer Vision): Fast edge detection method
- LLM (Large Language Model): AI-powered detection using Google Gemini
- CV+LLM: Tries CV first, falls back to LLM if needed (default)

Usage Examples:
    # Process a single image
    python get_speaker_names.py screenshot.png -v

    # Process a video with default 5-second intervals
    python get_speaker_names.py meeting.mp4 -v

    # Process video with custom interval and output file
    python get_speaker_names.py meeting.mp4 --interval 2.0 -o speakers.csv

    # Process only first 5 minutes with verbose output
    python get_speaker_names.py meeting.mp4 --duration 300 --verbose

    # Use EasyOCR and auto bottom-ROI when skipping panel detection
    python get_speaker_names.py frame.png --no-crop -v

Requirements:
- OpenCV (cv2)
- NumPy
- PIL (Pillow)
- EasyOCR (default OCR engine)
- FFmpeg (for video processing)
- Google Generative AI (optional, for LLM fallback)
- python-dotenv

Note: This script imports detection functions from get_speaker_bbox.py
"""

import argparse
import os
import re
import csv
import subprocess
import tempfile
import numpy as np
from typing import Optional
from PIL import Image
import easyocr
import logging
import difflib
from collections import Counter

# Import speaker bbox detection functions
from get_speaker_bbox import detect_speaker_bbox_cv, detect_speaker_bbox_llm


def perform_ocr(target_img: Image.Image, reader: easyocr.Reader = None, verbose: bool = False):
    """
    Perform OCR using EasyOCR only, with default settings.
    Returns a list of (text, confidence) tuples.
    """
    results = []
    if reader is None:
        reader = easyocr.Reader(['en'])
    target_array = np.array(target_img)
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
    Uses single-pass extraction with -vf fps=... if timestamps are regularly spaced.
    """
    result = {}
    if not timestamps:
        return result

    # Check if timestamps are regularly spaced
    if len(timestamps) > 1:
        interval = timestamps[1] - timestamps[0]
        is_regular = all(abs((timestamps[i] - timestamps[i-1]) - interval) < 1e-3 for i in range(2, len(timestamps)))
    else:
        is_regular = True

    if is_regular:
        # Use single-pass extraction
        fps = 1.0 / (timestamps[1] - timestamps[0]) if len(timestamps) > 1 else 1.0
        if verbose:
            print(f"Using single-pass FFmpeg extraction with fps={fps:.4f}")
        output_pattern = os.path.join(temp_dir, "frame_%04d.png")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"fps={fps}",
            output_pattern
        ]
        subprocess.run(cmd, capture_output=True, check=True)
        # Map output frames to timestamps
        for i, timestamp in enumerate(timestamps):
            frame_path = os.path.join(temp_dir, f"frame_{i+1:04d}.png")
            if os.path.exists(frame_path):
                result[timestamp] = frame_path
            else:
                if verbose:
                    print(f"Warning: Frame for timestamp {timestamp:.2f}s was not created")
        if verbose:
            print(f"Successfully extracted {len(result)}/{len(timestamps)} frames (single-pass)")
        return result
    else:
        # Fallback to old method for irregular timestamps
        if verbose:
            print("Timestamps are not regular, using multi-seek extraction.")
        # ...existing code for multi-seek extraction...
        cmd = ["ffmpeg", "-y", "-i", video_path]
        for i, timestamp in enumerate(timestamps):
            frame_number = frame_start_number + i
            frame_path = os.path.join(temp_dir, f"frame_{frame_number:04d}_{timestamp:.2f}s.png")
            cmd.extend([
                "-ss", str(timestamp),
                "-t", "0.04",
                "-vframes", "1",
                frame_path
            ])
        subprocess.run(cmd, capture_output=True, check=True)
        for i, timestamp in enumerate(timestamps):
            frame_number = frame_start_number + i
            frame_path = os.path.join(temp_dir, f"frame_{frame_number:04d}_{timestamp:.2f}s.png")
            if os.path.exists(frame_path):
                result[timestamp] = frame_path
            else:
                if verbose:
                    print(f"Warning: Frame at {timestamp:.2f}s was not created")
        if verbose:
            print(f"Successfully extracted {len(result)}/{len(timestamps)} frames (multi-seek)")
        return result


def detect_speaker_name_from_image(image_path: str, 
                                   reader: easyocr.Reader = None, 
                                   verbose: bool = True,
                                   debug_dir: str = None,
                                   no_crop: bool = False) -> str:
    """
    Detects speaker name from an image file.
    Automatically detects speaker panel bounding box and processes that region.
    Uses EasyOCR with default settings.
    """
    if not os.path.exists(image_path):
        return None
    
    # Load image
    img = Image.open(image_path)
    width, height = img.size
    
    # Determine which image to process
    if no_crop:
        # Skip speaker panel detection and use the entire image
        target_img = img
        region_name = "full_image"
        if verbose:
            print("Skipping speaker panel detection, using entire image for OCR")
            print(f"Crop dimensions (full image): {width}x{height}")
        
        # Save cropped/full image if debug directory is provided
        if debug_dir:
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            full_image_path = os.path.join(debug_dir, f"{base_name}_full_image.png")
            target_img.save(full_image_path)
            if verbose:
                print(f"Saved full image to: {full_image_path}")
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
        print(f"Performing OCR on {region_name} region...")
        # Report target (pre-OCR) image size
        tw, th = target_img.size
        print(f"Target OCR image size: {tw}x{th}")
    texts = perform_ocr(target_img, reader=reader, verbose=verbose)
    
    # Apply existing filtering and scoring logic but using texts list
    all_detected_names = []
    if verbose:
        print(f"Total OCR text candidates: {len(texts)}")
    for (text, confidence) in texts:
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


def sanitize_speaker_names(timestamps, names, similarity=0.8):
    """
    Post-processes the list of detected speaker names:
    - Groups similar names (e.g., 'ason Greenblum' and 'Jason Greenblum')
    - Replaces each with the most frequent (or longest) version in its group
    """
    groups = []
    used = set()
    for i, name in enumerate(names):
        if not name or name in used:
            continue
        group = [name]
        used.add(name)
        for j in range(i+1, len(names)):
            other = names[j]
            if other and other not in used:
                if difflib.SequenceMatcher(None, name.lower(), other.lower()).ratio() >= similarity:
                    group.append(other)
                    used.add(other)
        groups.append(group)
    canonical = {}
    for group in groups:
        count = Counter(group)
        most_common = count.most_common(1)[0][0]
        canonical_name = max([most_common] + group, key=len)
        for n in group:
            canonical[n] = canonical_name
    sanitized = [canonical.get(name, name) if name else "" for name in names]
    return sanitized


def process_video(video_path: str, interval: float, output_csv: str, 
                 max_duration: float = None, batch_size: int = 20, verbose: bool = False, debug: bool = False, no_crop: bool = False) -> bool:
    """
    Process a video file, extracting frames at intervals and detecting speaker names.
    Uses EasyOCR with default settings.
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
    
    # Initialize OCR reader once (reuse for all frames) if using EasyOCR
    import torch
    use_gpu = torch.cuda.is_available()
    reader = easyocr.Reader(['en'], gpu=use_gpu)
    if verbose:
        print("CUDA available:", torch.cuda.is_available())
        print("CUDA device count:", torch.cuda.device_count())
        if torch.cuda.is_available():
            print("Current device:", torch.cuda.current_device())
            print("Device name:", torch.cuda.get_device_name(torch.cuda.current_device()))
    
    # Calculate all timestamps that need to be processed
    all_timestamps = []
    current_time = 0.0
    while current_time < duration:
        all_timestamps.append(current_time)
        current_time += interval
    
    if verbose:
        print(f"Will process {len(all_timestamps)} frames in batches of {batch_size}")
    
    # Create temporary directory for extracted frames
    shm_base = '/dev/shm'
    use_shm = os.path.exists(shm_base) and os.access(shm_base, os.W_OK)
    if verbose:
        if use_shm:
            print(f"Using shared memory for temp frames: {shm_base}")
        else:
            print("/dev/shm not available or not writable, using disk for temp frames.")
    if debug:
        mode_suffix = "full_images" if no_crop else "cropped_regions"
        debug_dir = f"debug_{mode_suffix}_{os.path.basename(video_path).split('.')[0]}"
        os.makedirs(debug_dir, exist_ok=True)
        if no_crop:
            print(f"Debug mode: Full images will be saved in '{debug_dir}' directory")
        else:
            print(f"Debug mode: Cropped speaker regions will be saved in '{debug_dir}' directory")
        # Still need a temp dir for the full frames during processing
        if use_shm:
            temp_dir = os.path.join(shm_base, f"note_assistant_frames_{os.getpid()}")
            os.makedirs(temp_dir, exist_ok=True)
        else:
            temp_dir_context = tempfile.TemporaryDirectory()
            temp_dir = temp_dir_context.name
    else:
        debug_dir = None
        if use_shm:
            temp_dir = os.path.join(shm_base, f"note_assistant_frames_{os.getpid()}")
            os.makedirs(temp_dir, exist_ok=True)
        else:
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
                    # Save the full extracted frame in debug mode
                    if debug_dir:
                        base_name = os.path.splitext(os.path.basename(frame_path))[0]
                        full_image_path = os.path.join(debug_dir, f"{base_name}_full.png")
                        try:
                            Image.open(frame_path).save(full_image_path)
                            if verbose:
                                print(f"Saved full extracted frame to: {full_image_path}")
                        except Exception as e:
                            if verbose:
                                print(f"Failed to save full extracted frame: {e}")
                    # Detect speaker name (and save cropped region if applicable)
                    name = detect_speaker_name_from_image(
                        frame_path,
                        reader=reader,
                        verbose=verbose,
                        debug_dir=debug_dir,
                        no_crop=no_crop,
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
            # Sanitize names before saving
            sanitized_results = sanitize_speaker_names(timestamps, results)
            with open(output_csv, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['timestamp', 'speaker_name'])
                for ts, name in zip(timestamps, sanitized_results):
                    writer.writerow([ts, name])
            
            print(f"\nResults saved to: {output_csv}")
            print(f"Processed {len(results)} frames")
            detected_count = sum(1 for name in sanitized_results if name)
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
        elif use_shm and os.path.exists(temp_dir):
            import shutil
            shutil.rmtree(temp_dir)


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
        )
        
        if name:
            print(f"Detected speaker name: {name}")
        else:
            print("No speaker name detected.")


if __name__ == "__main__":
    main()

