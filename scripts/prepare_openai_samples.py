"""Opt-in, one-off speech production; the application never imports this module.

Defaults to a no-cost plan. Outputs and request caches stay under .local until
the rendered files have been reviewed and copied to the bundled sample folders.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from campaign_agent.creatives import EXAMPLES
from campaign_agent.adapters.local_media import write_media_manifest


ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "examples/ad-samples"
OUTPUT = ROOT / ".local/openai-samples"
MAX_AUDIO_BYTES = 20 * 1024 * 1024


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer credential to a redirected origin.
        return None


def load_key():
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        env = ROOT / ".env.local"
        if env.is_file():
            for line in env.read_text().splitlines():
                if line.startswith("OPENAI_API_KEY="):
                    key = line.partition("=")[2].strip().strip("\"'")
    if not key.startswith("sk-") or len(key) < 30:
        raise SystemExit("Configure OPENAI_API_KEY in the environment or ignored .env.local.")
    return key


def jobs(copy, model):
    result = []
    for example, context in zip(EXAMPLES, ("editing", "audiobook")):
        direction = copy["comparisons"][context]
        for take, label, name in example.takes:
            result.append({
                "id": context + "-comparison-" + take,
                "kind": "comparison", "context": context,
                "name": name, "preview": example.preview if take == "a" else None,
                "title": example.title, "label": label,
                "payload": {"model": model, "voice": direction["voice"],
                            "input": example.passage,
                            "instructions": direction["takes"][take],
                            "response_format": "wav"},
            })
    for ad in copy["ads"]:
        result.append({
            **ad, "id": "ad-" + ad["id"], "kind": "ad",
            "name": ad["id"] + ".mp4",
            "payload": {"model": model, "voice": ad["voice"],
                        "input": ad["script"], "instructions": ad["delivery"],
                        "response_format": "wav"},
        })
    if len(result) > 8 or sum(len(j["payload"]["input"]) for j in result) > 8000:
        raise ValueError("This authoring batch is limited to eight short recordings.")
    return result


def speech(payload, key, cache):
    encoded = json.dumps(payload, sort_keys=True).encode()
    path = cache / (hashlib.sha256(encoded).hexdigest() + ".wav")
    if path.is_file():
        duration(path)  # Decode cached media before reuse.
        return path
    request = Request("https://api.openai.com/v1/audio/speech", encoded,
                      {"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with build_opener(NoRedirects()).open(request, timeout=120) as response:
            data = response.read(MAX_AUDIO_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        exc.close()
        raise SystemExit(f"Speech API returned HTTP {status}. No automatic retry was made.") from None
    except (URLError, TimeoutError):
        raise SystemExit("Speech API connection failed. No automatic retry was made.") from None
    if len(data) > MAX_AUDIO_BYTES or not data.startswith(b"RIFF") or data[8:12] != b"WAVE":
        raise SystemExit("Speech API did not return a bounded WAV recording.")
    path.write_bytes(data)
    duration(path)
    return path


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *map(str, args)], check=True)


def duration(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=nw=1:nk=1", str(path)],
                            check=True, capture_output=True, text=True)
    seconds = float(result.stdout)
    if not 0 < seconds <= 60:
        raise ValueError("Use a valid recording of at most sixty seconds.")
    return seconds


def normalize(source, output, *, comparison, target_seconds=None):
    seconds = duration(source)
    # Preserve the eight-second comparison/caption contract and the deliberate
    # brisk/measured contrast. Reject large tempo changes; never cut a sentence.
    target = target_seconds or (min(seconds, 7.7) if comparison else max(seconds, 12))
    tempo = seconds / target
    if not 0.7 <= tempo <= 1.25:
        raise ValueError("Recording is too long or short for its pacing target. Revise delivery before retrying.")
    ffmpeg("-i", source, "-af", f"atempo={tempo:.8f},loudnorm=I=-18:TP=-2:LRA=7",
           "-ar", "48000", "-ac", "1", output)
    return duration(output)


def render(voice, poster, output, title, subtitle, cta, disclosure, seconds, font, staging):
    # A separate code-drawn typography layer; the generated artwork stays intact.
    from PIL import Image, ImageDraw, ImageFont
    overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 25))
    draw = ImageDraw.Draw(overlay)
    cream = (246, 241, 232, 255)
    draw.rectangle((0, 505, 1280, 640), fill=(0, 0, 0, 185))
    draw.rectangle((72, 360, 542, 422), fill=cream)
    for value, size, xy, color in (
        ("VOICE STUDIES / " + ("AUDIOBOOK" if "audiobook" in poster.name else "VIDEO EDITING"),
         18, (72, 70), cream),
        (title, 57, (72, 145), cream),
        (subtitle, 24, (72, 525), cream),
        (cta, 25, (94, 375), (23, 27, 32, 255)),
        (disclosure, 18, (72, 676), cream),
    ):
        draw.multiline_text(xy, value, font=ImageFont.truetype(str(font), size),
                            fill=color, spacing=10)
    layer = staging / "typography.png"
    overlay.save(layer)
    filters = (
        "[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,setsar=1[art];"
        "[art][1:v]overlay=0:0,"
        f"fade=t=in:st=0:d=0.35,fade=t=out:st={seconds - 0.25:.3f}:d=0.25[v]"
    )
    ffmpeg("-loop", "1", "-framerate", "24", "-i", poster,
           "-loop", "1", "-framerate", "24", "-i", layer, "-i", voice,
           "-filter_complex", filters, "-map", "[v]", "-map", "2:a",
           "-af", "apad", "-t", f"{seconds:.3f}",
           "-c:v", "libx264", "-preset", "fast", "-crf", "21", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true", help="Allow the eight paid speech API requests.")
    parser.add_argument("--model", default="gpt-4o-mini-tts")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--font", type=Path)
    args = parser.parse_args()
    copy = json.loads((SAMPLES / "copy.json").read_text())
    batch = jobs(copy, args.model)
    print(f"Batch: {len(batch)} recordings; {sum(len(j['payload']['input']) for j in batch)} spoken characters.")
    if not args.generate:
        print("No API calls made. Pass --generate to produce this batch into .local for review.")
        return
    if not args.output.resolve().is_relative_to((ROOT / ".local").resolve()):
        parser.error("Render into .local first; review before copying assets into the published fixtures.")
    if not all(shutil.which(command) for command in ("ffmpeg", "ffprobe")):
        parser.error("Install FFmpeg and ffprobe before generating speech.")
    try:
        import PIL  # noqa: F401 -- preflight before any paid request
    except ImportError:
        parser.error("Install Pillow in the authoring environment before generating speech.")
    candidates = [args.font] if args.font else [
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    font = next((p for p in candidates if p and p.is_file()), None)
    if font is None:
        parser.error("Supply a local TrueType font with --font.")
    for context in copy["comparisons"].values():
        if not (SAMPLES / context["poster"]).is_file():
            parser.error("Both authored scene images must exist before any API request.")
    key = load_key()
    cache = args.output / "cache"
    staging = args.output / "rendering"
    viewer = args.output / "viewer-media"
    ads = args.output / "ad-samples"
    for folder in (cache, staging, viewer, ads):
        folder.mkdir(parents=True, exist_ok=True)
    report = []
    for job in batch:
        print("Preparing " + job["id"], flush=True)
        raw = speech(job["payload"], key, cache)
        normalized = staging / (job["id"] + ".wav")
        targets = {"editing-comparison-a": 4.8, "editing-comparison-b": 6.5,
                   "audiobook-comparison-a": 6.0, "audiobook-comparison-b": 7.6}
        seconds = normalize(raw, normalized, comparison=job["kind"] == "comparison",
                            target_seconds=targets.get(job["id"]))
        poster = SAMPLES / copy["comparisons"][job["context"]]["poster"]
        transcript = job["payload"]["input"]
        if job["kind"] == "comparison":
            name = job["name"]
            if name.endswith(".mp3"):
                ffmpeg("-i", normalized, "-c:a", "libmp3lame", "-b:a", "192k", viewer / name)
            video = name if name.endswith(".mp4") else job["preview"]
            if video:
                render(normalized, poster, viewer / video,
                       "Same words.\nA different read.", textwrap.fill(transcript, 77),
                       job["label"], "Voice comparison / AI-generated voice and imagery", 8, font, staging)
        else:
            video = job["name"]
            render(normalized, poster, ads / video, job["headline"],
                   textwrap.fill(transcript, 77), job["cta"], copy["disclosure"],
                   seconds + 0.5, font, staging)
            # Keep the full script available to players independently of burned text.
            end = seconds + 0.5
            minutes, remainder = divmod(end, 60)
            stamp = f"00:{int(minutes):02d}:{remainder:06.3f}"
            (ads / (Path(video).stem + ".vtt")).write_text(
                f"WEBVTT\n\n00:00:00.000 --> {stamp}\n{transcript}\n")
        report.append({"id": job["id"], "model": args.model,
                       "source_seconds": duration(raw), "normalized_seconds": seconds})
    write_media_manifest(viewer, EXAMPLES)
    (args.output / "production-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Rendered into " + str(args.output) + ". Review before copying the media into examples/.")


if __name__ == "__main__":
    main()
