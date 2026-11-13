# Contextual creative for YouTube

A proof of concept for planning YouTube campaigns around what people are watching. It explores how a media buyer can find relevant video placements, pair each group with an ad and a matching product demo, and use delivery and viewer activity to plan the next test.

Placement discovery, draft saving, export and the two-take comparison run locally. If the workflow proves useful and there’s demand, it could become a standalone product or a tool for delivering campaign planning and testing services.

Start with the [product brief](docs/product-brief.md), [architecture](docs/architecture-plan.md), [design direction](docs/design-direction.md) and [build plan](docs/build-plan.md).

## Run the planner

Use Python 3.12 or newer, Node 22.12 or newer, and pnpm 10.33.0 to run the React planner. After building the frontend, start the Python server and open the private planner link printed in the terminal.

```sh
(cd web/planner && pnpm install --frozen-lockfile && pnpm build)
python3 scripts/placement_review.py serve --portable-demo wait
```

Choose **Try the offline example** on the home screen to open the campaign workspace and run the recorded agent against the fictional catalog. The workspace shows the completed steps, saved draft revision, placements and comparison links. **Resume preparation** continues a run interrupted in the same browser tab. Use **Placements** to search, edit selections or export placement URLs. Rebuild after editing the React source.

In the campaign workspace, review the setup, preview the bundled cuts and choose **Approve package**. **Export setup** downloads a JSON handoff with fictional placement labels. Review links allow switching between the examples whose content still matches the package. If the draft, comparison text or media changes, reload and review the package before approving it again. **Approval history** shows the saved contents of each approval recorded with a snapshot.

To rehearse campaign creation, ask **“Validate the campaign setup”** in chat or choose **Validate paused setup** in **Campaign setup**. Review the simulated account, creative groups, destinations and placement IDs, then choose **Approve and create paused campaign**. The workspace shows the separately saved provider read-back and simulated resource IDs. If creation is uncertain, **Check provider read-back** checks for that same operation. This flow uses the local simulated provider and a zero budget.

### Portable demo walkthrough

The portable demo uses bundled media, recorded agent responses and an authored delivery scenario. It needs no provider credentials or media generation. The default database is `.local/portable-demo.sqlite3`. Use `--draft-db` with a new path for a fresh run.

1. Prepare and approve the offline package, then validate and create its paused simulated setup.
2. In **Demo delivery**, open **Rehearse tagged comparison** for each group. Play Take A and Take B to the end and select one. Return to the planner and choose **Review demo delivery**. Each group's **All-time viewer link** row should show one arrival and one completion on a fresh run.
3. Choose **Recommend next test**. The `wait` fixture shows zero delivery and recommends waiting for evidence.
4. Stop the server and restart with `--portable-demo propose` using the same database and viewer port. Open the new private planner link, return to the approved workspace, choose **Review demo delivery**, then **Recommend next test**. The authored editing cohort shows one completion from four arrivals and the recommendation is **Test a shorter second take**. The observed viewer link counts remain separate. The same actions are available in chat with “Review demo delivery” and “Recommend the next test from the saved delivery review.”

The ordinary `serve` command uses the simulated setup and local viewer attribution without these authored delivery scenarios.

The optional Google Ads sandbox CLI uses a separate local draft database with an approved test package. Use the existing Ads OAuth grant in `.local/google/` and a Python environment with `google-auth` and `requests`. In a private config JSON, set `manager_id`, `account_id`, `logo_file` and `creatives`. Key `creatives` by the package's creative versions and provide `video_id`, `destination`, `headline`, `long_headline` and `description` for each. Supply approved test videos, public HTTPS destinations and a square PNG logo. The test package needs two groups with registered, distinct video targets.

```sh
python3 scripts/google_ads_sandbox.py --config CONFIG --draft-db SANDBOX_DB \
  --revision REVISION --fingerprint FINGERPRINT validate
```

Review the saved payload and setup ID after Google accepts validation. To approve creation, use the same options with `create-paused --setup-id SETUP_ID`. The CLI sends one paused create request and compares Google's read-back with the approved plan. If the response is uncertain, use `reconcile --setup-id SETUP_ID` to look up the same campaign. Store the CLI output in a private location.

To review the verified test campaign's delivery, start the planner with the same private config and database.

```sh
python3 scripts/placement_review.py serve --draft-db SANDBOX_DB --google-ads-reporting-config CONFIG
```

Choose **Review Google Ads delivery** in the approved campaign workspace or ask in chat. For example, “How is this campaign performing in Google Ads?” The planner queries the verified campaign and ad groups for the last seven completed dates in the account time zone. It saves ad-group totals and reported video placements separately from configured targets. Test-account reports can contain zero totals or empty rows. The ordinary planner starts in offline mode.

Once the report is saved, select **Recommend next test** or ask “Recommend the next test from the saved delivery review.” The recommendation uses that report, eligible arrivals and completions in its time window, and the current buyer correction from **Performance review**. The illustrative rule requires reported clicks and at least three eligible tagged arrivals, with fewer than half completing. The planner records workspace preview visits as rehearsals. Eligible visits are measured through the tagged link. Google Ads clicks remain a separate count. Recommendation uses the saved data and creates no draft.

For an offline attribution rehearsal, approve a new package, validate and create its paused simulated setup, then open the two tagged comparisons from **Ad viewer activity**. Play both takes and choose one. Click **Review ad viewer activity** or ask for it in chat to see arrivals and completions by ad. Counts cover all recorded visits through each tagged link, including rehearsals. Google Ads metrics keep their own date range and reporting level.

For a new Google Ads test setup, set `viewer_origin` in the private config to the public HTTPS origin of a compatible viewer serving the same verified setup journal. This generates the ad destinations before validation and read-back checks them after creation. Per-creative `destination` values are optional with this setting. Existing approved setups retain their original destinations. Use a new approved revision for tagged destinations.

After approval, choose a sample delivery scenario and click **Review performance**. The review saves fictional delivery and observed local viewer activity as separate evidence, then proposes a next test. Local completion is measured per verified visit for the approved comparison content. Visits without a verified content identity are shown separately. The sample delivery window and clicks belong to the fictional report.

When the review proposes a comparison test, use **Buyer correction** to specify what must stay fixed. Save it and run another review to see how the proposal changes. The constraint applies within that campaign. **Keep both takes unchanged** carries over to instruction edits when the takes and their comparison context match. **Keep the entire comparison unchanged** applies to the full comparison. The optional note records the reason.

After a review uses **Keep both takes unchanged**, choose **Prepare next test**. The offline agent loads that review and correction, drafts revised comparison instructions, and saves a new campaign revision for approval. The workspace shows the original and proposed wording and links to the original comparison. The revised comparison has its own content fingerprint and viewer activity. The recordings are reused. The new package needs approval before export.

Preparation resumes through **Resume preparation** after a refresh or interrupted request. Starting again from the same source review reuses its run. A changed package or buyer correction requires a fresh review before an unfinished run can save its draft. Wording comes from labelled, authored offline responses.

After approving the revised package, choose **Run instruction test**. Use **Rehearse instruction test** for internal checks and share **Open participant link** with viewers taking part in the experiment. Each link assigns the browser to the original or revised instructions. SQLite saves the assignment, and local storage keeps separate browser references for participant and rehearsal visits. Reopening the same link with the same browser, viewer port and database returns the same version and progress.

Use **Refresh results** to see immediate participant completions and arrivals for both versions, then **Review instruction test** for an agent assessment using those results and the current buyer correction. The saved assessment retains its evidence and is flagged when later participant activity or a correction calls for another review. The offline rules require at least 20 participant visits per version before considering another instruction change. This threshold is illustrative.

Under **Learning evidence**, choose **Save evidence snapshot** to record cumulative results at the current cutoff. New tests pin a five-minute window from each assigned arrival. A mature participant visit contributes one outcome, with a completion counted when the viewer finishes both takes and chooses within that window. Visits with an open window or missing measurement timestamps appear as unresolved. Rehearsals, authored fixtures and unknown sources appear in separate cohorts. Each new snapshot supersedes the previous one for the test. Visits recorded before source tracking appear under **Unknown source** in the immediate results.

For a test with a policy pinned at start, the snapshot also shows an offline recommendation to propose the revised wording for reuse, keep the original wording, or collect one more batch. The policy starts with a uniform prior per version and treats a lift of five percentage points as the improvement target. Reuse earns one decision unit if the effect exceeds that target and loses nine otherwise. Keeping earns zero in either case. These payoffs are illustrative. When starting a new test, the buyer can allow one extra batch of 10 visits after the first 40 participant visits have resolved, up to 50 total. Save a snapshot at 40 resolved visits before recruiting more. The policy recommends the extra batch only when its expected gain exceeds the 0.01-unit cost. After a saved snapshot recommends the batch, later snapshots show how many visits remain and defer the reuse or keep decision until the full batch resolves. The buyer controls recruitment. The recommendation uses the latest saved snapshot and supports up to 400 mature participant visits.

When the snapshot proposes reuse, choose **Save reuse finding**. In **Campaign draft**, open **Start a fresh brief**, enter the new title and goal, and choose the same comparison context. The sample workspace starts a separate brief revision and retains the previous approval history. A matching brief shows the tested wording, participant counts, and uncertainty. **Prepare wording draft** applies the wording to a new revision for package approval. **Retire finding** removes it from future reuse. A newer evidence snapshot or new participant visits can make a saved finding ineligible.

### Compare instruction policies offline

Run the versioned Bayesian policy and the fixed-lift baseline on the same simulated participant streams. The existing instruction-test assessment retains its native actions. The [saved comparison report](docs/instruction-policy-comparison.md) includes wrong reuse, missed improvements, extra visits, waiting, decision value, ties and baseline wins. Its rules and scenario assumptions are pinned in [the comparison specification](examples/instruction-policy-comparison.json).

```sh
python3 -B scripts/compare_instruction_policies.py --output /tmp/instruction-policy-comparison.md --json /tmp/instruction-policy-comparison.json
```

The command also exercises finding reuse after reopening a temporary SQLite database. To keep that example for the planner, add `--walkthrough-db /tmp/policy-walkthrough.sqlite3` with a new path, then run `python3 scripts/placement_review.py serve --portable-demo propose --draft-db /tmp/policy-walkthrough.sqlite3`. The report uses authored outcomes and the declared illustrative payoffs.

### Main model and placement discovery

For an approved package, choose **Changes → Instruction-test draft** and try **“Review this campaign performance and prepare the next instruction test if the evidence supports it.”** The chat agent reviews labelled sample delivery alongside recorded local viewer activity and the saved buyer correction. An eligible comparison review with **Keep both takes unchanged** can produce an unapproved instruction-only draft. The transcript's **Review evidence** disclosure retains the source counts and correction; the campaign workspace shows the revised instructions and approval state. You can also ask for a review alone, then choose the draft permission for a follow-up **“Prepare it.”**

**Changes** defaults to **Review only** for each new message. Choose **Placement draft** or **Instruction-test draft** to authorize that request's changes. The choice is saved with the run, shown in Agent activity and enforced before saving; message text and model calls cannot grant permission. Retries reuse the original choice. Older runs without a saved choice are read-only. **Try the offline example** explicitly authorizes its placement draft. Approval, export and launch remain separate actions.

The agent waits when there is insufficient evidence or a delivery gap, and explains missing approval or correction choices without changing the draft. Set or change the persistent correction in **Performance review**; conversational wording alone does not overwrite it. Chat uses the latest saved sample delivery scenario for the current package, defaulting to the balanced authored sample. Changed evidence needs a fresh review. Approval remains an explicit workspace action. All provider integration checks use simulated responses.

After starting an approved instruction experiment in the workspace, ask **“How is the instruction test doing?”** Chat saves an assessment of assigned visits and completions for the original and revised versions and shows them under **Experiment evidence**. If the assessment supports another test, select **Changes → Instruction-test draft** and send **“Prepare it.”** The draft uses the approved revised version as its baseline. The workspace also offers **Review instruction test** and **Plan next step**.

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

Without a frontend build, this opens standalone placement review. **New request** and **Campaign** appear after installing the planner dependencies and running `pnpm --dir web/planner build`; reopen the placement page after building. Search results and imported proposals stay on the current page. Leaving or reloading warns while that session work or unsaved selections remain, including after selected placements have been saved.

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

The [bundled viewer media](examples/viewer-media/README.md) uses original scripts and graphics with Flite synthetic speech. Open **Preview local creatives** to play the captioned previews and follow their comparison links. Ordinary `serve` preserves an existing `.local/viewer-media/` directory for packages approved with locally generated media. Portable demo mode always uses the bundled versions.

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
