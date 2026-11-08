# Contextual creative for YouTube

A proof of concept for planning YouTube campaigns around what people are watching. It explores how a media buyer can find relevant video placements, pair each group with an ad and a matching product demo, and use delivery and viewer activity to plan the next test.

Placement discovery, draft saving, export and the two-take comparison run locally. If the workflow proves useful and there’s demand, it could become a standalone product or a tool for delivering campaign planning and testing services.

Start with the [product brief](docs/product-brief.md), [architecture](docs/architecture-plan.md), [design direction](docs/design-direction.md) and [build plan](docs/build-plan.md).

## Run the planner

Use Python 3.12 or newer, Node 22.12 or newer, and pnpm 10.33.0 to run the React planner. After building the frontend, start the Python server and open the private planner link printed in the terminal.

```sh
pnpm --dir web/planner install --frozen-lockfile
pnpm --dir web/planner build
python3 scripts/placement_review.py serve
```

Choose **Try the offline example** on the home screen to open the campaign workspace and run the recorded agent against the fictional catalog. The workspace shows the completed steps, saved draft revision, placements and comparison links. **Resume preparation** continues a run interrupted in the same browser tab. Use **Placements** to search, edit selections or export placement URLs. Rebuild after editing the React source.

In the campaign workspace, review the setup, preview the cuts and choose **Approve package**. Both placement groups and their generated media must be ready. **Export setup** downloads a JSON handoff with fictional placement labels. Review links allow switching between the examples whose content still matches the package. If the draft, comparison text or media changes, reload and review the package before approving it again. **Approval history** shows the saved contents of each approval recorded with a snapshot.

After approval, choose a sample delivery scenario and click **Review performance**. The review saves fictional delivery and observed local viewer activity as separate evidence, then proposes a next test. Local completion is measured per verified visit for the approved comparison content. Visits without a verified content identity are shown separately. The sample delivery window and clicks belong to the fictional report.

When the review proposes a comparison test, use **Buyer correction** to specify what must stay fixed. Save it and run another review to see how the proposal changes. The constraint applies within that campaign. **Keep both takes unchanged** carries over to instruction edits when the takes and their comparison context match. **Keep the entire comparison unchanged** applies to the full comparison. The optional note records the reason.

After a review uses **Keep both takes unchanged**, choose **Prepare next test**. The offline agent loads that review and correction, drafts revised comparison instructions, and saves a new campaign revision for approval. The workspace shows the original and proposed wording and links to the original comparison. The revised comparison has its own content fingerprint and viewer activity. The recordings are reused. The new package needs approval before export.

Preparation resumes through **Resume preparation** after a refresh or interrupted request. Starting again from the same source review reuses its run. A changed package or buyer correction requires a fresh review before an unfinished run can save its draft. Wording comes from labelled, authored offline responses.

After approving the revised package, choose **Run instruction test**. **Open instruction test** opens one viewer link that assigns each browser to the original or revised instructions. The assignment is saved in SQLite and an opaque browser reference is kept in local storage. Reopening the link with the same browser, viewer port and database returns the same version and progress.

The test counts only visits assigned through that link. Use **Refresh results** to see completions and arrivals for both versions, then **Review instruction test** for an agent assessment using those results and the current buyer correction. The saved assessment retains its evidence and is flagged when later activity or a correction calls for another review. The offline rules require at least 20 assigned visits per version before considering another instruction change. This threshold is illustrative. The displayed completion rates describe the recorded visits.

### Review models

**Review mode** defaults to **Offline**. To enable OpenRouter for instruction-test assessments, provide `OPENROUTER_API_KEY` in the server environment and explicitly configure permitted models at startup. Replace the model placeholder below with a compatible `:free` model ID. Repeat the flag to offer several models.

```sh
python3 scripts/placement_review.py serve --openrouter-review-model 'provider/model:free'
```

Choose **OpenRouter** and a model in the test panel before reviewing. Each run allows one request, at most 512 output tokens and a 30-second HTTP timeout. The request filters routes to zero prompt, completion and per-request prices and disables provider fallback. The adapter requests a strict JSON schema from a provider that supports it. The application also validates the assessment and buyer constraint. [OpenRouter structured outputs](https://openrouter.ai/docs/guides/features/structured-outputs) · [Provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)

The provider receives the two instruction texts, their observed results and the buyer correction. **Review provenance and usage** shows the selected and reported model, evidence reference, prompt version, provider request ID and reported usage. Unavailable usage is shown as unknown. Credentials are read server-side when dispatching.

The model selects a constrained reason code. The application checks that code against the captured counts and buyer correction, then generates the assessment's title and factual wording itself. Older saved assessments are displayed with regenerated factual wording and a notice to review again.

An interrupted run can reuse a saved provider receipt through **Resume preparation**. A request with an unknown outcome or a failed response consumes its allowance. A new deliberate review creates a new operation. Integration verification uses simulated responses, including receipt recovery, timeouts, malformed output, rejected permissions and budget checks.

### Next-test drafting models

**Prepare next test** also defaults to recorded offline wording. To offer OpenRouter drafting, enable models separately with `--openrouter-draft-model 'provider/model:free'` when starting the server. This flag can be combined with the review-model flag. The server uses the same `OPENROUTER_API_KEY` environment variable and one-request, zero-price, 512-token limits.

After a performance review with an active **Keep takes** correction, choose **Draft mode** and **Draft model**, then **Prepare next test**. The model receives the saved sample delivery, observed local activity, comparison text and buyer correction. It selects approved components for playback, comparison focus and a neutral choice. The application validates those IDs and assembles the viewer text: both takes must be finished, with no preferred take or added product claims. Free-form provider text is rejected. The workspace shows original and proposed wording, the correction and inference provenance. Recordings and placements remain fixed, and the new revision requires approval.

Resume uses the saved provider receipt without another request. The application rechecks the approved content and active correction before dispatch, when accepting the response and when saving the revision. The writer also verifies that the saved wording matches its approved components. A rejected start clears its placeholder; an interrupted start retains the exact operation for retry, and an unavailable saved run never starts a different campaign. A changed package or correction requires a fresh review. Provider tests use authored simulated responses; live drafting quality has not been verified.

### Continue from an experiment assessment

After **Review instruction test**, choose **Plan next step**. The agent checks the latest saved assessment against current activity, the buyer correction and the approved package. If it calls for more evidence, the run records **Waiting for more evidence** without creating a draft or making a drafting inference request. Review again after more activity before planning another step.

If the verified assessment supports another instruction test, the agent prepares a new unapproved revision. **Next draft mode** defaults to **Offline**, with the separately configured OpenRouter drafting models available as an option. The current approved revised comparison becomes the next baseline; this does not declare it a winner. The draft links its source experiment and assessment, preserves the recordings and placements, and requires package approval before a new experiment can start. Earlier experiments, reviews and viewer assignments remain intact. Repeated or interrupted preparation reuses its run and provider receipt.

## Placement review

Run the local workspace with Python 3.12 or newer and open the planner link printed in the terminal. The default mode uses fictional candidates and needs no external credentials. Add `--live-youtube` after providing your own YouTube Data API key in the ignored `.local/google/youtube-data-key.json` file as a JSON object with a `key` field. Search phrases are editable for each creative. In live mode, the export contains the selected video URLs for one creative, one per line. Verify those URLs in the intended Google Ads campaign before using them.

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

## Viewer comparison

On macOS with FFmpeg installed, run `python3 -m scripts.prepare_viewer_media` once. It uses the local Samantha voice and writes the original demo media to ignored `.local/viewer-media/`. Start the placement server and open **Preview local creatives** to play the captioned previews and follow their comparison links.

The comparison records local viewer activity in the draft database. A visit keeps its original creative reference when the viewer switches examples. Playing both takes through and choosing one records one completion per visit and example version. The viewer retries pending activity with the same event IDs after a refresh in the same tab.

The planner link contains a private token for the current server process. Keep that link local and use the separate viewer link for the comparison. The viewer runs at `http://127.0.0.1:8766` by default. If that port is busy, pass `--viewer-port 8876` and reuse the same port and database on each restart so saved viewer links and pending activity in the same tab still work. Planner access uses the seeded local operator, client and brand. Hosted staff authentication is a separate milestone.

## Offline agent preparation

Run `python3 -m campaign_agent.agent` to prepare the fictional Text to Speech campaign from the recorded demo request. The command prints a run ID before it starts and returns the saved draft revision and ambiguous catalog entries. Use `python3 -m campaign_agent.agent --resume RUN_ID` to continue an interrupted run. The planner opens the saved sample draft for review.

The recorded decisions support the included demo request, local fictional catalog and instruction-test workflow. The run preserves existing placements and stops if the draft changes while it is preparing. Approve and export the resulting package through the planner.

## Engineering checks

```sh
python3 -m unittest discover -s tests -v
```

See the [engineering workflow](docs/engineering-workflow.md) for design, test and review expectations. The [synthetic context example](examples/synthetic-context/metadata.json) is authored test data. Prior Google Ads test-account reads verified access and returned empty reports. The build uses a zero-cost budget across media, models, hosting and ads.
