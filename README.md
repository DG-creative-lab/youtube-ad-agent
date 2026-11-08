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

### Main model and placement discovery

The campaign workspace includes a saved conversation. Send a request, answer the agent's clarification or send a follow-up in the same campaign. **Saved conversations** reopens previous dialogue after a refresh or a browser restart. Each message retains its run and draft revision; the campaign draft always shows the latest saved state. Questions can receive a reply without creating a draft. Changing the main model or choosing **New request** starts a new conversation within the same campaign.

Offline dialogue is an authored simulation: try `Help me`, then `Audiobook production, please.` Choose another catalog and ask `More like that`, or ask `What have we saved?` Model context contains up to 20 prior messages within an 8 KB serialized dialogue budget; the full transcript stays saved. Before a provider call, the app also fits the complete request—including the current message, schemas, settings and tool results—to the 32 KB transport limit. Omitted dialogue or tool history is explicitly marked. A follow-up stops unfinished work in that conversation. A stale browser tab must load the latest messages before sending. Runs still advance through ordinary HTTP requests, one step at a time. Reopen an unfinished conversation to resume it; SSE, token streaming and background execution are not included.

The model chooses reply topics and clarification reasons. Application code supplies the wording and reads current campaign state for status claims; chat cannot approve, export or launch. Older unconstrained replies remain in storage but appear as needing verification rather than being displayed as verified assistant text. A server prompt update can apply to a new turn in the same conversation while existing runs retain their original settings.

The composer keeps the **Main model** menu and send arrow inside the message box. **Catalog** and **Import** pills reveal their options on demand. Start with **Simulated agent**, or choose **Simulated agent · inspect first** to see a different tool order. These are authored test responses, not live LLM reasoning. Choose a catalog, describe the task and send the message. The main model can read the brief and buyer corrections, inspect source material, request classification, save an unapproved draft, or ask a necessary question. It receives each tool result and any rejected-tool observation before choosing the next action. The activity panel shows the actual requested tools and pinned model.

**Use your own catalog** imports a JSON array of up to 200 rows, using `video_id`, `description`, `source` (`creator_supplied`, `licensed` or an authored `synthetic` fixture), and `source_reference`. Imported catalog facts are immutable and scoped to the campaign's client and brand. Public YouTube API results stay in the separate search/review workflow. Selected rows keep their source references, while ambiguous classifications stay held for review. Catalog candidates are labelled as unverified inventory in the manual export.

To offer a tool-capable OpenRouter main model, set `OPENROUTER_API_KEY` in the server environment and explicitly enable its `:free` ID:

```sh
python3 scripts/placement_review.py serve --agent-model 'provider/model:free'
```

Selecting that model enables its real inference path. Model selection is pinned to a saved conversation and each run; changing the picker starts a new conversation, while interrupted runs retain their original settings. The server keeps the workspace/operator default, and the browser preserves the current selection across refreshes. Existing review and instruction-drafting actions inherit the main-model selection; simulated main profiles use their recorded offline responses. The earlier review/draft CLI flags remain available for API compatibility.

Classification is routed automatically through `PlacementClassifier`. This slice uses a clearly labelled simulated decision adapter, backed by authored local rules. It does not call live Jev or claim measured classification accuracy. A live Jev adapter requires a separately configured and evaluated budgeted route. Users do not pick specialist models per task. Counts, deduplication, scope, catalog provenance and approval checks remain in Python.

Placement runs allow at most eight main-model requests, each with at most 512 output tokens and a 30-second HTTP timeout. OpenRouter requests require compatible tool support, disable fallback and cap route prices at zero. One specialist request is allowed per run; repeated classification reuses its saved receipt. The harness records request reservations and receipts outside the tool transaction, then commits each accepted tool result with its draft change. Unknown request outcomes are not retried automatically. An invalid tool can return a recoverable observation; exhaustion and missing context stop with a visible question or message. Package approval remains separate.

Instruction-test assessments still use validated reason codes, and proposed viewer instructions use application-approved neutral components. Their receipts, exact evidence references and usage remain available in the saved records. All integration checks used simulated provider responses; live main-model quality and Jev accuracy remain unverified. [OpenRouter tool calling](https://openrouter.ai/docs/guides/features/tool-calling) · [Provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)

### Continue from an experiment assessment

After **Review instruction test**, choose **Plan next step**. The agent checks the latest saved assessment against current activity, the buyer correction and the approved package. If it calls for more evidence, the run records **Waiting for more evidence** without creating a draft or making a drafting inference request. Review again after more activity before planning another step.

If the verified assessment supports another instruction test, the agent prepares a new unapproved revision. Drafting inherits the conversation's main-model choice, with recorded offline responses for simulated profiles. The current approved revised comparison becomes the next baseline; this does not declare it a winner. The draft links its source experiment and assessment, preserves the recordings and placements, and requires package approval before a new experiment can start. Earlier experiments, reviews and viewer assignments remain intact. Repeated or interrupted preparation reuses its run and provider receipt.

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
