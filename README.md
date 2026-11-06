# Contextual creative for YouTube

A proof of concept for planning YouTube campaigns around what people are watching. It explores how a media buyer can find relevant video placements, pair each group with an ad and a matching product demo, and use delivery and viewer activity to plan the next test.

Placement discovery, draft saving and export run locally. The viewer experience is at the storyboard stage. If the workflow proves useful and there’s demand, it could become a standalone product or a tool for delivering campaign planning and testing services.

Start with the [product brief](docs/product-brief.md), [architecture](docs/architecture-plan.md), [design direction](docs/design-direction.md) and [build plan](docs/build-plan.md).

## Placement review

Run the local workspace with Python 3.12 or newer and open [http://127.0.0.1:8765](http://127.0.0.1:8765). The default mode uses fictional candidates and needs no credentials. Add `--live-youtube` after providing your own YouTube Data API key in the ignored `.local/google/youtube-data-key.json` file as a JSON object with a `key` field. Search phrases are editable for each creative. In live mode, the export contains the selected video URLs for one creative, one per line. Verify those URLs in the intended Google Ads campaign before using them.

```sh
python3 scripts/placement_review.py serve
```

**Save to campaign** records both placement groups against the local seed brief. Reopen the workspace to load the latest saved revision. If another tab saves first, review the merged draft and choose how to resolve overlapping edits before saving again. The placement and request limits apply across both groups.

Sample selections and registered live-mode catalog selections are stored in separate campaigns in the ignored `.local/campaign-drafts.sqlite3` database. Live YouTube search selections stay in the browser session and remain available for export.

In a second terminal, generate the example proposals.

```sh
mkdir -p .local
python3 scripts/placement_review.py assign examples/placement-review/catalog.json > .local/sample-proposals.jsonl
```

Use **Import creative assignments** to load the example output in sample mode. For real assignments, supply a JSON catalog with `video_id`, `description` and `source` for each video. Use `creator_supplied` or `licensed` only for material you have permission to classify, and `synthetic` for rehearsal. Review ambiguous items and approve the proposed group as a batch if appropriate.

To save real placements, add a `source_reference` to each independent catalog entry, such as the identifier of a creator handoff or a license record. Generate the proposals on the same local installation with `python3 scripts/placement_review.py assign your-catalog.json --register-catalog > .local/catalog-proposals.jsonl`, then import them. Registration records your source declaration. It does not verify the underlying permission. Older proposals can still be reviewed and exported. Register and reselect those placements to save a new revision.

The default assignment uses local rules. To explicitly enable the billed Jev adapter, provide `OPENROUTER_API_KEY` server-side and pass `--paid-jev-limit N` to `assign`, where `N` covers the catalog and is at most 500. The model receives the permitted descriptions. It proposes a creative or sends the item to review. The current probability cutoffs are provisional. [OpenRouter Jev 1.14](https://openrouter.ai/typesafe/jev-1.14)

## Engineering checks

```sh
python3 -m unittest discover -s tests -v
```

See the [engineering workflow](docs/engineering-workflow.md) for design, test and review expectations. The [synthetic context example](examples/synthetic-context/metadata.json) is authored test data. Prior Google Ads test-account reads verified access and returned empty reports. The build uses a zero-cost budget across media, models, hosting and ads.
