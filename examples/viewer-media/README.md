# Bundled viewer media

These clips and readings use original passages in [the example definitions](../../campaign_agent/creatives.py). The 25 November 2026 refresh uses OpenAI-generated speech (Marin for the editing scene, Cedar for the audiobook), original imagegen scene artwork, and locally composed video. Both takes use identical wording and the same voice within each context, with different delivery directions and pacing. These are unbranded synthetic demonstrations, not recordings from ElevenLabs or evidence of a product's performance.

Playback uses the bundled MP4 and MP3 files without credentials or network access. The editing videos and audiobook preview remain eight seconds, matching the application's caption contract; complete spoken passages fit within that window. [Ad samples and authoring notes](../ad-samples/README.md) contain four additional ad-copy variations, generation directions and migration instructions. The opt-in OpenAI authoring command renders into ignored local staging for review.

For the older zero-cost local-synthesis alternative, build [Flite v2.2](https://github.com/festvox/flite/tree/v2.2) with the CMU SLT voice and install FFmpeg, then run from the repository root. That path uses different voices and simple graphics. Flite's [license and attribution](https://github.com/festvox/flite/blob/v2.2/COPYING) apply to that synthesizer.

```sh
python3 -m scripts.prepare_viewer_media --flite /path/to/flite/bin/flite --output examples/viewer-media
```

Regeneration changes content hashes. The planner requires a fresh approval for changed text or media. Both authoring tools write `media-manifest.json`, binding the example definitions to the exact recording hashes. Ordinary serving accepts a local override only when that manifest matches both the current definitions and all five files. Without a manifest, all five files must be byte-identical to the current bundle. Missing, old, malformed or partially updated pairings stop startup with recovery instructions before creating campaign state. File changes after startup become unavailable and block approval/export until restart with a valid pairing.

Portable demo mode uses this bundled folder. To recover an incompatible override, back it up and regenerate it, or replace it with this bundle. Copy the five media files and their generated manifest together, restart, and review the new package. Moving the entire override folder aside also restores the default bundled media. Do not create a new manifest over unknown legacy recordings: regenerate from the current passages so the authoring command records the pairing. Saved private catalogs retain their old immutable definitions and media.
