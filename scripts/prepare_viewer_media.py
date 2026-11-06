"""Generate local synthetic speech and original comparison media on macOS."""

from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from campaign_agent.creatives import EXAMPLES


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / ".local/viewer-media"
EDIT = ("drawbox=x=179:y=69:w=282:h=222:color=0x303030:t=fill,"
        "drawbox=x=289:y=134:w=62:h=92:color=0x101010:t=fill,"
        "drawbox=x=289:y=134:w=62:h=92:color=0xfaf9f6:t=fill:enable='gte(t,2.6)'")
BOOK = ("drawbox=x=227:y=66:w=186:h=227:color=0x444444:t=3,"
        "drawbox=x=244:y=82:w=152:h=194:color=0xc8c4bb:t=fill,"
        "drawbox=x=315:y=82:w=5:h=194:color=0x88847c:t=fill")


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *args], check=True)


def video(voice, art, destination):
    ffmpeg(
        "-f", "lavfi", "-i", "color=c=0x171717:s=640x360:r=24", "-i", str(voice),
        "-vf", art, "-af", "apad", "-t", "8", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(destination),
    )


def main():
    if not all(shutil.which(command) for command in ("say", "ffmpeg")):
        raise SystemExit("Generate these local fixtures with macOS say and FFmpeg.")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=OUTPUT) as folder:
        staging = Path(folder)
        for example in EXAMPLES:
            for (take, _, name), rate in zip(example.takes, (194, 144), strict=True):
                voice = staging / "voice.aiff"
                subprocess.run(["say", "-v", "Samantha", "-r", str(rate), "-o", str(voice), example.passage], check=True)
                if voice.stat().st_size < 4096:
                    raise SystemExit("macOS did not produce a usable voice recording. Check the local voice installation.")
                if name.endswith(".mp4"):
                    video(voice, EDIT, staging / name)
                else:
                    ffmpeg("-i", str(voice), "-c:a", "libmp3lame", str(staging / name))
                    if take == "a":
                        video(voice, BOOK, staging / example.preview)
                voice.unlink()
        for asset in staging.iterdir():
            asset.replace(OUTPUT / asset.name)
    print(f"Local demo media prepared in {OUTPUT}")


if __name__ == "__main__":
    main()
