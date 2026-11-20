"""Build a fresh fixture from the authored catalogue, media and application schema."""
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.placement_review import build_handler
from campaign_agent.bootstrap.runtime import DEMO_MEDIA_DIR
from .storage import compress_snapshot


def seed_database():
    with TemporaryDirectory() as folder:
        path = Path(folder) / "preview.sqlite"
        build_handler(False, path, operator_token="seed", demo_scenario="propose", media_dir=DEMO_MEDIA_DIR)
        return path.read_bytes()


def journey_databases():
    # Build-time authored outcomes only; no fixture injection command is exposed at runtime.
    from scripts.compare_instruction_policies import prepare_walkthrough
    snapshots = {}
    with TemporaryDirectory() as folder:
        prepare_walkthrough(Path(folder) / "exercise.sqlite", checkpoint=snapshots.__setitem__)
    return snapshots


if __name__ == "__main__":
    Path(__file__).with_name("seed.data").write_bytes(compress_snapshot(seed_database()))
    for phase, snapshot in journey_databases().items():
        Path(__file__).with_name(f"journey-{phase}.data").write_bytes(compress_snapshot(snapshot))
