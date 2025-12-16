import argparse
import os
import re
import csv
import subprocess
import tempfile
import numpy as np
import json
from PIL import Image
import easyocr


def load_bounding_box_from_json(json_path: str) -> dict:
    """
    Load bounding box coordinates from a JSON file.
    
    Args:
        json_path: Path to the JSON file containing bounding box data
        
    Returns:
        Dictionary with bounding box coordinates or None if not found/error
    """
    try:
        with open(json_path, 'r') as f:
            content = f.read()
        
        # Try to parse as JSON first
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # If JSON parsing fails, try to evaluate as Python literal (for dict format)
            import ast
            data = ast.literal_eval(content)
        
        if data.get('found_speaker_panel', False) and data.get('bounding_box'):
            bbox = data['bounding_box']
            return {
                'x': bbox['x'],
                'y': bbox['y'],
                'width': bbox['width'],
                'height': bbox['height']
            }
        else:
            print(f"No speaker panel found in JSON file: {json_path}")
            return None
    except Exception as e:
        print(f"Error loading bounding box from JSON file {json_path}: {e}")
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


def extract_frames_batch(video_path: str, timestamps: list, temp_dir: str, verbose: bool = False) -> dict:
    """
    Extract multiple frames from a video at specified timestamps using FFmpeg.
    
    Args:
        video_path: Path to the video file
        timestamps: List of timestamps in seconds
        temp_dir: Directory to save extracted frames
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
        for timestamp in timestamps:
            frame_path = os.path.join(temp_dir, f"frame_{timestamp:.2f}.png")
            cmd.extend([
                "-ss", str(timestamp),
                "-t", "0.04",  # Very short duration to get just one frame
                "-vframes", "1",
                frame_path
            ])
        
        # Execute FFmpeg command
        subprocess.run(cmd, capture_output=True, check=True)
        
        # Check which frames were successfully created
        for timestamp in timestamps:
            frame_path = os.path.join(temp_dir, f"frame_{timestamp:.2f}.png")
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
        
        for timestamp in timestamps:
            frame_path = os.path.join(temp_dir, f"frame_{timestamp:.2f}.png")
            if extract_frame_at_time(video_path, timestamp, frame_path):
                result[timestamp] = frame_path
        
        return result


def process_video(video_path: str, interval: float, output_csv: str, 
                 bbox_json_path: str = None, 
                 max_duration: float = None, batch_size: int = 20, verbose: bool = False) -> bool:
    """
    Process a video file, extracting frames at intervals and detecting speaker names.
    
    Args:
        video_path: Path to the video file
        interval: Time interval in seconds between frame extractions
        output_csv: Path to output CSV file
        bbox_json_path: Path to JSON file containing speaker panel bounding box coordinates
        max_duration: Maximum duration in seconds to process (None = entire video)
        batch_size: Number of frames to extract in each batch
        verbose: If True, print progress information
        
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
    
    # Initialize OCR reader once (reuse for all frames)
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
    with tempfile.TemporaryDirectory() as temp_dir:
        results = []
        timestamps = []
        
        # Process frames in batches
        for batch_start in range(0, len(all_timestamps), batch_size):
            batch_end = min(batch_start + batch_size, len(all_timestamps))
            batch_timestamps = all_timestamps[batch_start:batch_end]
            
            if verbose:
                print(f"Processing batch {batch_start//batch_size + 1}/{(len(all_timestamps) + batch_size - 1)//batch_size} "
                      f"({len(batch_timestamps)} frames)...")
            
            # Extract frames for this batch
            extracted_frames = extract_frames_batch(video_path, batch_timestamps, temp_dir, verbose=verbose)
            
            # Process each frame in the batch
            for timestamp in batch_timestamps:
                if verbose:
                    progress = (batch_start + (timestamp - batch_timestamps[0]) / interval) / len(all_timestamps) * 100
                    print(f"Processing frame at {timestamp:.2f}s ({progress:.1f}%)...")
                
                frame_path = extracted_frames.get(timestamp)
                
                if frame_path and os.path.exists(frame_path):
                    # Detect speaker name
                    name = detect_speaker_name_from_image(frame_path, reader=reader, bbox_json_path=bbox_json_path, verbose=False)
                    
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
            return True
        except Exception as e:
            print(f"Error writing CSV file: {e}")
            return False


def detect_speaker_name_from_image(image_path: str, 
                                   reader: easyocr.Reader = None, 
                                   bbox_json_path: str = None,
                                   verbose: bool = True) -> str:
    """
    Detects speaker name from an image file.
    Uses bounding box from JSON file if provided, otherwise processes the entire image.
    
    Args:
        image_path: Path to the image file
        reader: EasyOCR reader instance (if None, will create one)
        bbox_json_path: Path to JSON file containing speaker panel bounding box coordinates
        verbose: If True, print progress information
        
    Returns:
        Detected speaker name or None if not found
    """
    if not os.path.exists(image_path):
        return None
    
    # Load image
    img = Image.open(image_path)
    width, height = img.size
    
    # Determine which image to process
    if bbox_json_path:
        bbox = load_bounding_box_from_json(bbox_json_path)
        if bbox:
            # Use bounding box from JSON
            crop_left = bbox['x']
            crop_top = bbox['y']
            crop_right = bbox['x'] + bbox['width']
            crop_bottom = bbox['y'] + bbox['height']
            
            # Ensure coordinates are within image bounds
            crop_left = max(0, min(crop_left, width))
            crop_top = max(0, min(crop_top, height))
            crop_right = max(crop_left, min(crop_right, width))
            crop_bottom = max(crop_top, min(crop_bottom, height))
            
            target_img = img.crop((crop_left, crop_top, crop_right, crop_bottom))
            region_name = "json_bbox"
            if verbose:
                print(f"Using bounding box from JSON: ({crop_left}, {crop_top}, {crop_right}, {crop_bottom})")
        else:
            # Fall back to full image if JSON loading failed
            target_img = img
            region_name = "full"
            if verbose:
                print("Falling back to full image processing")
    else:
        # No bbox_json_path provided, use entire image
        target_img = img
        region_name = "full"
    
    # Initialize OCR reader if not provided
    if reader is None:
        if verbose:
            print("Initializing OCR reader...")
        reader = easyocr.Reader(['en'])
    
    # Perform OCR on the target image
    all_detected_names = []
    
    if verbose:
        print(f"Performing OCR on {region_name} region...")
    
    target_array = np.array(target_img)
    results = reader.readtext(target_array)
    
    for (bbox, text, confidence) in results:
        if confidence > 0.5:
            cleaned = re.sub(r'[^\w\s]', '', text).strip()
            if len(cleaned) > 2:
                words = cleaned.split()
                if len(words) >= 2 or (len(words) == 1 and any(c.isupper() for c in cleaned)):
                    all_detected_names.append((cleaned, confidence, region_name))
                    if verbose:
                        print(f"  -> Added as candidate: '{cleaned}' (confidence: {confidence:.2f})")
    
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
    parser.add_argument("--bbox-json", help="Path to JSON file containing speaker panel bounding box coordinates.")
    parser.add_argument("--batch-size", type=int, default=20,
                       help="Number of frames to extract in each batch (default: 20). Higher values may be faster but use more memory.")
    parser.add_argument("-v", "--verbose", action="store_true",
                       help="Print verbose progress information.")
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
        
        success = process_video(args.input_file, args.interval, output_csv, 
                               bbox_json_path=args.bbox_json, 
                               max_duration=args.duration, batch_size=args.batch_size, verbose=args.verbose)
        if not success:
            exit(1)
    else:
        # Process image file (original functionality)
        name = detect_speaker_name_from_image(args.input_file, 
                                              bbox_json_path=args.bbox_json, verbose=True)
        
        if name:
            print(f"Detected speaker name: {name}")
        else:
            print("No speaker name detected.")


if __name__ == "__main__":
    main()

