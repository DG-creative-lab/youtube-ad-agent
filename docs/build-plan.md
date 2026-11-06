# Campaign agent build plan

6 November 2026 · [Product brief](product-brief.md) · [Architecture](architecture-plan.md) · [Design direction](design-direction.md) · [Engineering workflow](engineering-workflow.md)

## Application deliverable

Build one local workflow for the ElevenLabs Text to Speech brief. A buyer gives the agent a goal and gets a saved campaign package for video editing and audiobook production tutorials. Each group has proposed placements, a playable cut and a link to its comparison demo. The buyer approves one package for manual handoff. After trying the viewer experience, the buyer sees a review based on recorded local activity and labelled sample delivery. The next run uses an explicit buyer correction and an evidence-linked hypothesis to propose a follow-up test.

Target a complete walkthrough by **Friday 13 November**. Reserve **Monday 16 November** for a clean setup check and application packaging before the recorded **18:30 GMT** deadline. These are planning targets. Keep the build at zero cost across media, models, hosting and advertising.

## Milestones

| Target | Build | Acceptance check |
| --- | --- | --- |
| **1. Save a campaign · 6–9 Nov** | Start from the existing Python server and placement workspace. Add SQLite with a versioned seed brief, brand rules, campaign runs and immutable package revisions. Save placement selections against their context and source. Keep the existing search, catalog assignment and export paths working. Inventory the original scripts, footage and audio in parallel with this work. | Reopen the app after a restart. The brief revision, two context groups and selections are still there. Save an edit and confirm the previous revision still resolves. Existing placement export returns the same canonical video URLs. |
| **2. Make both viewer paths playable · 9–10 Nov** | Produce two short captioned cuts with owned or otherwise permitted assets. Build one comparison page with editing and audiobook content. Bind each CTA to a creative version and its matching example. Record arrival, playback start, playback finish and choice. | Follow both CTAs in a browser. Each opens the promised example. Finishing both takes and choosing one records one completion for that visit and example. Test refresh, a duplicate event, and a missing sample with a usable recovery path. |
| **3. Give the agent the workflow · 10–11 Nov** | Add one Python tool dispatcher for the preparation job. Load approved context, gather permitted candidates, assemble a draft from available creative assets, validate it and request one package review. Use recorded model responses for the offline run. Put the OpenRouter integration behind the same model interface when permitted access is available. Add a handoff with objective, format, budget, dates, per-group placements, cut and CTA, plus a place to record actual settings and ad IDs. | Start with one buyer request. The run reaches a reviewable package without the buyer operating each tool. Approve and export it. Change a cut, destination or placement and verify that the new revision needs its own review. Interrupt a preparation job and reopen it at the last saved step. |
| **4. Close the loop · 12 Nov** | Add a sample `CampaignReporting` adapter. Save delivery and local demo events as observations. Compute completion per tagged arrival for each eligible creative version. Store a buyer correction and a scoped finding or hypothesis. Have a new run retrieve both and propose the next test. | Run the review twice with different evidence. Low delivery leads to a delivery check. Sufficient arrivals with low completion can lead to a demo test. A partial report leaves unsupported breakdowns unknown. The next brief references the correction and the specific observations that influenced it. |
| **5. Verify and package · 13 and 16 Nov** | Freeze the working path on Friday. Run the walkthrough on a fresh local database, then use Monday for fixes, the recording and setup notes. Show where product approval ends and manual Google Ads setup begins. Include the actual results of any optional runtime or sandbox checks. | A reviewer can follow the documented setup, play both viewer paths and reproduce the two runs without credentials. Every part of the walkthrough identifies its evidence source and shows which capability was exercised. |

## First implementation slice

Build this slice in Python and SQLite with the existing browser screen. React and TypeScript are for the fuller planner. Use the same backend API for both. The viewer comparison uses plain HTML, CSS and JavaScript.

1. Keep `scripts/placement_review.py serve` and `assign` as developer entry points. Extract the discovery, catalog classification and export behavior into callable functions only where the web or agent workflow needs them. Keep public YouTube search in its native review flow. Use independently supplied or fictional catalog material for model assignment.
2. Add the SQLite store and load one versioned brief with two contexts, approved claims and asset references. Store app state under `.local/`. The first browser change is **Save to campaign** in placement review. Persist the campaign and context, video IDs and provenance. Reload the saved selection in the planner.
3. Store each package revision as the exact brief and policy references, placement groups, creative versions, destinations and proposed launch settings. An approval points to that revision. Export the current approved package for handoff. A material edit requires a new approval, with the earlier package retained in history. Record actual provider bindings separately if a buyer supplies them.

Start the viewer path as soon as the creative and destination IDs exist. Use original recordings if suitable ElevenLabs output is unavailable within the zero-cost and rights constraints. Label the source of the audio shown in the application.

Use an opaque local visit ID and a stable event ID. Count one completion per visit and example version after two distinct takes finish and the viewer chooses one. Attribute activity to the example actually played and retain the original CTA version separately if the viewer switches contexts.

## First tool contracts

The agent and the web app enter through application commands. Resolve authority from the saved run. Bind reads and draft changes to its workspace, allowed sources and mandate. Use structured inputs and results throughout.

| Tool | Input and result | First adapter |
| --- | --- | --- |
| `load_campaign_context` | Run reference → approved knowledge versions, permitted assets and relevant memory references | SQLite |
| `propose_placements` | Context and allowed catalog reference → proposed IDs, source references and ambiguous items for review | Existing rules and fictional catalog. Jev stays opt-in subject to cost and permission. |
| `save_draft_package` | Run and expected draft revision plus the proposed package → a new revision or validation issues | SQLite and local asset checks |
| `get_campaign_delivery` | Bound campaign and date window → snapshot with source, reporting level, dates, coverage and status | Sample adapter first. Verified Google Ads test reads support a later read-only adapter. |
| `save_review_proposal` | Scoped observations and proposed hypothesis → a review record with evidence references | SQLite |

The buyer approves a package through the UI. The first runtime can read and prepare drafts. Save the job and its planned step before running tools. Commit each accepted draft change and its step outcome together, so a restart can reuse the result. A later activation command will check the saved grant and current policy before dispatch. Attach tool call status and evidence IDs to the run activity log.

## Release checks

- **Authority and recovery.** Exercise the actual dispatcher with fake adapters. A wrong workspace, stale revision, cancelled run or injected instruction cannot cause a write. A repeated accepted command returns its recorded result or resumes the same work. Tool responses and activity logs contain no credentials.
- **Placement evidence.** Preserve provenance and the distinction between candidate, selected and reported. Measure acceptance, reassignment and abstention on a permitted, human-labelled sample before claiming classification quality. Record whether a result came from local rules or a model.
- **Measurement.** Keep replayed model decisions, sample delivery and real local viewer events visibly labelled. Preserve report coverage and native grain. Show the numerator and denominator for viewer completion. An incomplete report can support a request for more evidence.
- **Product value.** In the walkthrough, show the time and buyer actions from brief to reviewable package. Record how many actions required judgment and whether a second run reused the prior evidence. Treat real-world adoption and lift as pilot questions.

## Optional runtime and later integration gates

- **DeepSeek Harness experiment.** After the tool boundary exists, spend at most one day before the Friday freeze on a pinned profile with one read tool and one draft tool. Inspect the exposed tool list and verify it contains no shell and receives no ad credentials. Exercise a scoped child, cancellation, process restart and runtime swap against the same saved campaign. Check OpenRouter routing when authorized, using replay for offline lifecycle checks. Adopt the runner only if it passes and reduces the code we own. Use the direct dispatcher and replay path for the application if the experiment runs past the cutoff or leaves an acceptance check open.
- **Live reporting and activation.** Add the Google Ads read adapter independently of writes. Validate the exact campaign type, targeting and report grain first. Keep manual handoff if a writable configuration cannot preserve the contextual placements. With separate authorization, verify a validation-only request and then a paused test-account write with read-back. Test stale grants, unknown write outcomes, reconciliation and duplicate dispatch with a fake provider first. A paid pilot is a separate milestone for delivery, inventory and outcome claims.
- **Product expansion.** Schedule report-triggered reviews once repeatable reads exist. Add provider subscriptions, external MCP, user-authored recipes or another ad platform when there is a real workflow for each. Use the same typed product commands and capability checks.
