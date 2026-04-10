"""Extract frames from Gallan Goodiyaan video to verify subtitles."""

import subprocess
import sys
from pathlib import Path

def extract_frame(video_path: Path, output_path: Path, timestamp: str = "00:00:05"):
    """Extract a single frame from the video at given timestamp."""
    cmd = [
        "ffmpeg", "-y",
        "-ss", timestamp,
        "-i", str(video_path),
        "-frames:v", "1",
        str(output_path)
    ]
    print(f"Extracting frame at {timestamp}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"✓ Frame saved to: {output_path} ({output_path.stat().st_size / 1024:.1f} KB)")
        return True
    else:
        print(f"✗ Failed: {result.stderr}")
        return False

if __name__ == "__main__":
    # Find Gallan Goodiyaan video
    output_dir = Path("output")
    videos = list(output_dir.rglob("*Gallan*/final/final_karaoke.mp4"))
    
    if not videos:
        print("Gallan Goodiyaan video not found!")
        sys.exit(1)
    
    video = videos[-1]
    print(f"Testing video: {video}")
    print(f"Size: {video.stat().st_size / 1048576:.1f} MB\n")
    
    # Extract frames at different timestamps (spaced throughout 4:38 song)
    test_frames = [
        "00:00:10",  # Early
        "00:00:30",  # Still early
        "00:01:00",  # 1 minute
        "00:02:00",  # 2 minutes
        "00:03:00",  # 3 minutes
        "00:04:00",  # Near end
    ]
    
    print("Extracting frames to verify subtitle positioning:\n")
    for ts in test_frames:
        frame_path = Path(f"test_frame_gallan_{ts.replace(':', '')}.png")
        extract_frame(video, frame_path, ts)
    
    print("\nAll frames extracted. Check the PNG files to verify:")
    print("  - Subtitle size (should be LARGE ~72px)")
    print("  - Subtitle position (should be centered, ~250px from bottom)")
    print("  - Font rendering (Hindi/English characters)")
    print("  - Highlight color (yellow for active word)")
