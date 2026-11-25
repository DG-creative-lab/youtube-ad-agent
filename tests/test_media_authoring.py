"""Cost and output safeguards for the opt-in media authoring command."""
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import prepare_openai_samples as authoring


class MediaAuthoringTests(unittest.TestCase):
    def test_default_plan_neither_loads_credentials_nor_calls_provider(self):
        with TemporaryDirectory() as folder:
            target = Path(folder) / "output"
            with patch("sys.argv", ["prepare_openai_samples", "--output", str(target)]), \
                    patch.object(authoring, "load_key") as key, \
                    patch.object(authoring, "speech") as speech, redirect_stdout(StringIO()):
                authoring.main()
            key.assert_not_called()
            speech.assert_not_called()
            self.assertFalse(target.exists())

    def test_generation_cannot_overwrite_bundled_media_directly(self):
        with patch("sys.argv", ["prepare_openai_samples", "--generate", "--output",
                                 str(authoring.ROOT / "examples/viewer-media")]), \
                patch.object(authoring, "speech") as speech, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                authoring.main()
        speech.assert_not_called()

    def test_provider_failure_is_not_retried_or_saved_and_does_not_echo_credentials(self):
        with TemporaryDirectory() as folder, patch.object(authoring, "build_opener") as opener:
            opener.return_value.open.side_effect = HTTPError(
                "https://api.openai.com/v1/audio/speech", 429, "private provider detail", {}, None)
            with self.assertRaises(SystemExit) as raised:
                authoring.speech({"input": "Original sample."}, "sk-private-test-value", Path(folder))
            self.assertEqual(str(raised.exception), "Speech API returned HTTP 429. No automatic retry was made.")
            self.assertEqual(opener.return_value.open.call_count, 1)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_overlong_comparison_is_rejected_before_any_audio_can_be_cut_off(self):
        with patch.object(authoring, "duration", return_value=14), \
                patch.object(authoring, "ffmpeg") as ffmpeg:
            with self.assertRaisesRegex(ValueError, "too long"):
                authoring.normalize(Path("source.wav"), Path("target.wav"), comparison=True)
        ffmpeg.assert_not_called()


if __name__ == "__main__":
    unittest.main()
