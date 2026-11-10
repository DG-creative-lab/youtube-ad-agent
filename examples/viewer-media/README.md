# Bundled viewer media

These clips and readings use the original passages in [the example definitions](../../campaign_agent/creatives.py) and the graphics in [the media generator](../../scripts/prepare_viewer_media.py). The two takes use different pacing from the CMU SLT synthetic voice in [Flite v2.2](https://github.com/festvox/flite/tree/v2.2). Flite's [license and attribution](https://github.com/festvox/flite/blob/v2.2/COPYING) apply to the upstream synthesizer. Only the rendered media is bundled here.

Playback uses the bundled MP4 and MP3 files. To regenerate them, build Flite with the SLT voice and install FFmpeg, then run from the repository root.

```sh
python3 -m scripts.prepare_viewer_media --flite /path/to/flite/bin/flite --output examples/viewer-media
```

Regeneration can change the content hashes. The planner requires a fresh approval for changed media.
