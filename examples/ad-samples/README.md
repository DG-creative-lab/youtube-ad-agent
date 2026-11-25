# Voice studies · sample ads

25 November 2026. Four original, unbranded ad concepts for the application's
voice-comparison use cases. These are authored samples, with no live advertising,
performance evidence, product endorsements or claims about ElevenLabs output.
The rendered voice and imagery are AI-generated, as disclosed in each video.

| Context | Variation | Preview | Creative idea |
| --- | --- | --- | --- |
| Video editing | A | [Play](editing-a.mp4) | The cut is ready. Is the voice? |
| Video editing | B | [Play](editing-b.mp4) | Same scene. Different feeling. |
| Audiobook | A | [Play](audiobook-a.mp4) | Make the first line worth following. |
| Audiobook | B | [Play](audiobook-b.mp4) | A whole story starts with one voice. |

[copy.json](copy.json) contains each hook, primary text, complete spoken script,
call to action, voice and delivery direction. The adjacent VTT files contain the
full scripts; the videos also display the words. These are distinct ad-copy
directions, not a controlled experiment. The existing in-app comparisons keep
the same passage across both takes so listeners can compare delivery instead.

OpenAI `gpt-4o-mini-tts` generated the recordings, using Marin for video editing
and Cedar for audiobook material. The built-in imagegen tool generated the two
scene images; [image-prompts.json](image-prompts.json) retains the exact prompts.
FFmpeg renders the 1280 × 720 H.264/AAC videos, with a separately drawn typography
layer. Audio is normalized to -18 LUFS, with pitch-preserving pacing adjustments.
No music, cloned voices, stock footage or third-party passages are used.

## Reproduce or revise

The application plays bundled media offline and does not load an OpenAI key.
The separate authoring command defaults to a no-cost plan:

```sh
python3 -m scripts.prepare_openai_samples
```

For deliberate paid regeneration, install the optional authoring dependencies
in an ignored environment, with FFmpeg and a local TrueType font available:

```sh
python3 -m venv .local/media-venv
.local/media-venv/bin/python -m pip install -r requirements-media.txt
.local/media-venv/bin/python -m scripts.prepare_openai_samples --generate
```

The command reads `OPENAI_API_KEY` from its process environment or ignored
`.env.local`; it never prints the key. It permits eight short recordings per
batch, caches raw speech by request content, makes no automatic paid retries,
and renders only under `.local/`. The comparison output includes a generation
manifest binding each example definition to the exact media hashes. Review before
copying the five media files and that manifest together into `examples/` or a
local override. An older override that lacks a matching pairing is rejected by
ordinary startup; it is never silently labelled with the new passages.
Keep rejected generations, transcription checks and account-specific results in
`.local/`, outside Git. Changing the script or delivery direction creates a new
cache entry and may incur another request. A cached batch can be rendered again
without another speech request.

The Speech API model used for this dated batch is scheduled to shut down on
6 January 2027. The static assets continue to work offline; future production
should move to the current audio API rather than treat this authoring script as
a long-lived application integration. [OpenAI speech documentation](https://developers.openai.com/api/docs/guides/text-to-speech).

## Carry into direct-acquisition-agent

PR #138 already contains copies of the five comparison media files. It also
duplicates the passages and instructions in
`src/acquisition/adapters/youtube_fixture.py`; updating audio alone leaves the
displayed passage wrong. Copy the new files from `examples/viewer-media/` into
that repository's `examples/youtube-media/`, and update both fixture passages and
the editing instruction from this repository's `campaign_agent/creatives.py`.
Carry the AI disclosure and these provenance notes as well.

These four standalone ad videos are additional creative candidates. They are
not automatically substituted for comparison previews or admitted to the target
application's media allowlist. Carry this folder and its copy manifest when
adding ad-variation selection there. Do not give an ad's script the comparison
passage's captions.

The current comparison IDs stay stable; exact content and media hashes change.
Both applications must require a fresh review/approval for the changed content.
Retain old immutable private catalogs and saved approval snapshots. Merging the
target application's own main branch cannot import files from this separate
YouTube repository. No changes to PR #138 are made by this local asset update.
