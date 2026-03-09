import subprocess
import os


def video_to_mp3(input_path: str) -> str:
    """Extracts audio from video and returns the path to the mp3 file."""
    output_path = input_path.rsplit('.', 1)[0] + ".mp3"

    # -vn: no video
    # -acodec libmp3lame: standard mp3 encoder
    # -q:a 2: High quality variable bitrate (~190 kbps)
    cmd = [
        "ffmpeg", "-i", input_path,
        "-vn", "-acodec", "libmp3lame", "-q:a", "2",
        output_path, "-y"
    ]
    subprocess.run(cmd, check=True)
    return output_path


def video_to_gif(input_path: str) -> str:
    """Converts video to a high-quality GIF."""
    output_path = input_path.rsplit('.', 1)[0] + ".gif"

    # GIF conversion in FFmpeg requires two steps for high quality:
    # 1. Generate a color palette 2. Apply palette to the video
    # We'll use a complex filter to do it in one pass
    # scale=480:-1 reduces size to 480px wide while keeping aspect ratio
    filter_complex = "fps=12,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"

    cmd = [
        "ffmpeg", "-i", input_path,
        "-vf", filter_complex,
        output_path, "-y"
    ]
    subprocess.run(cmd, check=True)
    return output_path


def split_video(input_path: str, start_time: str, end_time: str) -> str:
    """Splits a video file between start_time and end_time."""
    output_path = input_path.rsplit('.', 1)[0] + "_split.mp4"

    # -ss: start time, -to: end time
    # -c copy: splits without re-encoding (very fast)
    cmd = [
        "ffmpeg", "-i", input_path,
        "-ss", start_time, "-to", end_time,
        "-c", "copy", output_path, "-y"
    ]
    subprocess.run(cmd, check=True)
    return output_path
