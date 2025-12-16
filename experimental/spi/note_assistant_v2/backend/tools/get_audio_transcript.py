import argparse
import csv
import os
import subprocess
import tempfile

import whisper


def extract_audio_from_video(video_file_path: str, audio_file_path: str, duration: float = None) -> bool:
    """
    Extracts audio from a video file and saves it as an MP3 file using ffmpeg.

    Args:
        video_file_path (str): The path to the input video file.
        audio_file_path (str): The path to save the output MP3 audio file.
        duration (float, optional): Duration in seconds to extract. If None, extracts entire audio.

    Returns:
        bool: True if extraction was successful, False otherwise.
    """
    if not os.path.exists(video_file_path):
        print(f"Error: Video file not found at '{video_file_path}'")
        return False

    try:
        # Build ffmpeg command
        cmd = ['ffmpeg', '-i', video_file_path, '-y']  # -y to overwrite output file
        
        if duration is not None:
            cmd.extend(['-t', str(duration)])
            print(f"Extracting audio for first {duration} seconds")
        
        # Audio extraction options
        cmd.extend([
            '-vn',  # No video
            '-acodec', 'mp3',  # Audio codec
            '-ar', '16000',  # Sample rate (16kHz is good for speech)
            '-ac', '1',  # Mono audio
            audio_file_path
        ])
        
        # Run ffmpeg
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"Successfully extracted audio to '{audio_file_path}'")
            return True
        else:
            print(f"Error: ffmpeg failed with return code {result.returncode}")
            print(f"Error output: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("Error: ffmpeg not found. Please install ffmpeg.")
        return False
    except Exception as e:
        print(f"An error occurred during audio extraction: {e}")
        return False


def transcribe_audio(audio_file_path: str, model_name: str = "base") -> dict:
    """
    Transcribes audio using OpenAI's Whisper model.

    Args:
        audio_file_path (str): The path to the audio file.
        model_name (str): The Whisper model to use (tiny, base, small, medium, large).

    Returns:
        dict: The transcription result with timestamps.
    """
    try:
        model = whisper.load_model(model_name)
        result = model.transcribe(audio_file_path, word_timestamps=True)
        return result
    except Exception as e:
        print(f"An error occurred during transcription: {e}")
        return None


def save_transcript_to_csv(transcript_result: dict, output_csv_path: str) -> bool:
    """
    Saves the transcript to a CSV file with timestamps and dialogue.

    Args:
        transcript_result (dict): The result from Whisper transcription.
        output_csv_path (str): The path to save the CSV file.

    Returns:
        bool: True if successful, False otherwise.
    """
    try:
        with open(output_csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['start_time', 'end_time', 'text']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            
            # Extract segments with timestamps
            for segment in transcript_result.get('segments', []):
                writer.writerow({
                    'start_time': f"{segment['start']:.2f}",
                    'end_time': f"{segment['end']:.2f}",
                    'text': segment['text'].strip()
                })
        
        print(f"Transcript saved to '{output_csv_path}'")
        return True
    except Exception as e:
        print(f"An error occurred while saving CSV: {e}")
        return False


def process_media_file(input_file_path: str, output_csv_path: str, model_name: str = "base", duration: float = None) -> bool:
    """
    Processes a media file (.mp4 or .mp3) to extract transcript.

    Args:
        input_file_path (str): Path to the input media file.
        output_csv_path (str): Path to save the output CSV file.
        model_name (str): Whisper model to use for transcription.
        duration (float, optional): Duration in seconds to process. If None, processes entire file.

    Returns:
        bool: True if successful, False otherwise.
    """
    if not os.path.exists(input_file_path):
        print(f"Error: Input file not found at '{input_file_path}'")
        return False
    
    file_extension = os.path.splitext(input_file_path)[1].lower()
    
    # Determine if we need to extract audio or can use the file directly
    if file_extension == '.mp3':
        audio_file_path = input_file_path
        temp_audio_file = None
    elif file_extension == '.mp4':
        # Create temporary audio file
        temp_audio_file = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        audio_file_path = temp_audio_file.name
        temp_audio_file.close()
        
        # Extract audio from video
        if not extract_audio_from_video(input_file_path, audio_file_path, duration):
            if temp_audio_file:
                os.unlink(audio_file_path)
            return False
    else:
        print(f"Error: Unsupported file format '{file_extension}'. Supported formats: .mp4, .mp3")
        return False
    
    try:
        # Transcribe audio
        print(f"Transcribing audio using Whisper model '{model_name}'...")
        transcript_result = transcribe_audio(audio_file_path, model_name)
        
        if transcript_result is None:
            return False
        
        # Save to CSV
        success = save_transcript_to_csv(transcript_result, output_csv_path)
        
        return success
    finally:
        # Clean up temporary audio file if created
        if file_extension == '.mp4' and temp_audio_file:
            try:
                os.unlink(audio_file_path)
            except OSError:
                pass


def main():
    """
    Main function to handle command-line arguments for audio transcription.
    """
    parser = argparse.ArgumentParser(
        description="Extract audio transcript from .mp4 or .mp3 files using Whisper and save as CSV."
    )
    parser.add_argument("input_file", help="Path to the input media file (.mp4 or .mp3).")
    parser.add_argument("-o", "--output", help="Path for the output CSV file. If not provided, it will be the same as the input file with a .csv extension.")
    parser.add_argument("-m", "--model", default="base", choices=["tiny", "base", "small", "medium", "large"], 
                       help="Whisper model to use for transcription (default: base).")
    parser.add_argument("-d", "--duration", type=float, help="Duration in seconds to process from the beginning of the file. If not specified, processes the entire file.")
    
    args = parser.parse_args()

    # Determine output file path
    if args.output:
        output_file = args.output
    else:
        base_name = os.path.splitext(args.input_file)[0]
        output_file = f"{base_name}_transcript.csv"

    # Process the media file
    success = process_media_file(args.input_file, output_file, args.model, args.duration)
    
    if success:
        print(f"Transcript successfully saved to '{output_file}'")
    else:
        print("Failed to process the media file.")
        exit(1)

if __name__ == "__main__":
    main()