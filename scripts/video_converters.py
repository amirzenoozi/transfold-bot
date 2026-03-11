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


def video_to_round(input_path: str) -> str:
    """
    Converts a video to the Telegram-compatible Round (Telescope) format.
    Ensures 1:1 aspect ratio and 384x384 resolution.
    """
    output_path = input_path.rsplit('.', 1)[0] + "_round.mp4"

    # Filter breakdown:
    # 1. crop=ih:ih: sets width to match height (square) from the center
    # 2. scale=384:384: resizes to Telegram standard
    # 3. setspts=PTS-STARTPTS: ensures smooth playback
    filter_complex = "crop='min(iw,ih):min(iw,ih)',scale=384:384"

    cmd = [
        "ffmpeg", "-i", input_path,
        "-vf", filter_complex,
        "-vcodec", "libx264",
        "-crf", "20",  # High quality
        "-preset", "fast",
        "-acodec", "aac",  # Round videos require audio
        "-strict", "experimental",
        output_path, "-y"
    ]

    # Run the command
    import subprocess
    subprocess.run(cmd, check=True)
    return output_path


def get_actual_video_duration(input_path: str) -> float:
    """Returns the actual duration of the video in seconds."""
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", input_path]
    output = subprocess.check_output(cmd).decode("utf-8")
    return float(output)


def remove_audio(input_path: str) -> str:
    """
    Removes the audio stream from a video file.
    This uses stream copying, so it is extremely fast.
    """
    output_path = input_path.rsplit('.', 1)[0] + "_muted.mp4"

    cmd = [
        "ffmpeg", "-i", input_path,
        "-an",  # Remove audio
        "-vcodec", "copy",  # Copy video stream without re-encoding
        output_path, "-y"
    ]

    import subprocess
    subprocess.run(cmd, check=True)
    return output_path


def add_text_watermark(video_path, text):
    """Adds a text watermark with black text and white shadow."""
    output_path = video_path.rsplit('.', 1)[0] + "_text_wm.mp4"

    # drawtext filter settings:
    # x,y: position (10 pixels from bottom-right)
    # shadowcolor, shadowx, shadowy: creates the white outline/shadow
    filter_str = (
        f"drawtext=text='{text}':fontcolor=black:fontsize=24:"
        f"shadowcolor=white:shadowx=2:shadowy=2:"
        f"x=w-tw-10:y=h-th-10"
    )

    cmd = ["ffmpeg", "-i", video_path, "-vf", filter_str, "-codec:a", "copy", output_path, "-y"]
    subprocess.run(cmd, check=True)
    return output_path


def add_image_watermark(video_path, watermark_path):
    """Overlays an image watermark, scaled down to 10% of video width."""
    output_path = video_path.rsplit('.', 1)[0] + "_img_wm.mp4"

    # filter_complex:
    # [1:v]scale=w=main_w*0.1:h=-1 (scales watermark to 10% width)
    # overlay=main_w-overlay_w-10:main_h-overlay_h-10 (bottom-right)
    filter_str = "[1:v]scale=w=main_w*0.1:h=-1[wm];[0:v][wm]overlay=main_w-overlay_w-10:main_h-overlay_h-10"

    cmd = ["ffmpeg", "-i", video_path, "-i", watermark_path, "-filter_complex", filter_str, "-codec:a", "copy",
           output_path, "-y"]
    subprocess.run(cmd, check=True)
    return output_path
