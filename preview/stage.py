"""Stage only the deployed app, generated frontend and permitted authored fixtures."""
from pathlib import Path
import shutil
from subprocess import check_output
import sys


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "app.py", "requirements.txt", "vercel.json", "scripts/placement_review.py",
    "placement-review/index.html", "preview/seed.data", "examples/tts-performance/delivery.json",
    "preview/journey-plan.data", "preview/journey-wait.data", "preview/journey-learning.data",
    "examples/placement-review/catalog.json", "web/planner/dist/index.html",
}
RUNTIME_PREFIXES = ("campaign_agent/", "web/brand/", "web/viewer/",
                    "examples/placement-review/", "examples/tts-performance/")
RUNTIME_PREVIEW = {"preview/application.py", "preview/storage.py", "preview/build_seed.py", "preview/providers.py"}


def stage(destination):
    tracked = check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    paths = REQUIRED | RUNTIME_PREVIEW | {
        path for path in tracked if path.startswith(RUNTIME_PREFIXES)
        or path.startswith("examples/viewer-media/") and Path(path).suffix in {".mp3", ".mp4"}
    }
    assets = sorted((ROOT / "web/planner/dist/assets").glob("*"))
    if not any(file.suffix == ".js" for file in assets) or not any(file.suffix == ".css" for file in assets):
        raise ValueError("Build the planner before staging a preview.")
    paths.update(asset.relative_to(ROOT).as_posix() for asset in assets if asset.is_file())
    destination.mkdir(exist_ok=False)
    for path in sorted(paths):
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)


if __name__ == "__main__":
    stage(Path(sys.argv[1]))
