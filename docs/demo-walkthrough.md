# Demo walkthrough

11 November 2026 · [Release checkpoint](build-plan.md#release-checkpoint--11-november-2026) · [Comparison report](instruction-policy-comparison.md)

## Recording plan

Allow six to eight minutes for the edited walkthrough. Use a desktop viewport for the campaign workspace and a narrow viewport for one viewer comparison. Keep the source labels, saved revision and approval controls visible.

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:45 | A new offline request becomes two placement groups and a campaign package. | The buyer gives the planner a brief. The recorded agent and fictional catalog make this example reproducible. |
| 0:45–1:20 | Approve the package, export its handoff, and validate and create the paused simulated setup. | Package approval and setup approval are explicit buyer actions. The read-back belongs to the local simulator. |
| 1:20–2:15 | Play both takes and choose a reading in the editing and audiobook viewers. | These interactions create actual local events. Each tagged viewer group records one arrival and one completion. |
| 2:15–3:00 | Review delivery, show the wait state, then restart with the propose scenario. | The authored report changes. The previously recorded local viewer counts stay separate and persist. |
| 3:00–4:00 | Save a keep-takes correction, prepare and approve an instruction test, and save its empty evidence snapshot. | The experiment pins the two wordings, measurement window and budget. The policy waits for its initial evidence. |
| 4:00–5:30 | Switch to the prepared learning example, start a fresh editing brief, restart, and prepare its wording draft. | This section uses authored experiment outcomes. The saved finding brings its source counts and uncertainty into a compatible brief. The buyer reviews the new draft before approval. |
| 5:30–6:30 | Show the offline comparison and a baseline-win example. | The fixed rules and shared simulations expose tradeoffs, including ties and mistaken reuse. The report measures behavior under its declared assumptions. |

For the learning section, show a caption reading **Authored experiment example · 2/20 versus 18/20** before showing the finding card. Its participant counters are populated by the offline setup script through the real application commands. The caption distinguishes that prepared evidence from the viewer interactions recorded during this walkthrough.

## Prepare a clean installation

Use Python 3.12 or newer, Node 22.12 or newer and pnpm 10.33.0. A fresh public checkout and uncached package installation require internet access. The running portable demo and comparison use local resources.

```sh
git clone https://github.com/DG-creative-lab/youtube-ad-agent.git youtube-ad-agent-demo
cd youtube-ad-agent-demo
env -i PATH="$PATH" python3 -B -m unittest discover -s tests -q
env -i PATH="$PATH" pnpm --dir web/planner install --frozen-lockfile
env -i PATH="$PATH" pnpm --dir web/planner build
demo_dir=$(mktemp -d)
```

Use the same shell for the commands below so `demo_dir` remains available. Open the private planner link printed by each server process and keep that link out of the recording. Open the viewer URL on the same computer for the local demonstration. The viewer binds to `127.0.0.1`. A recipient on another computer needs to follow these setup steps and open the viewer link from their own running instance.

## Prepare, approve and play

```sh
env -i PATH="$PATH" python3 -B scripts/placement_review.py serve --portable-demo wait --draft-db "$demo_dir/portable.sqlite3"
```

1. Choose **Try the offline example**. Show the two contexts, fictional placements and completed agent steps.
2. Choose **Approve package**, then **Export setup**. The downloaded JSON identifies the fictional package and manual Google Ads handoff.
3. In **Campaign setup**, choose **Validate paused setup**, then **Approve and create paused campaign**. Show **Verified · simulated campaign paused** and its provider read-back.
4. In **Demo delivery**, open **Rehearse tagged comparison** for video editing. Play Take A and Take B through to the end, then choose a take. Reload to show the saved choice.
5. Repeat for audiobook production. Return to the planner and choose **Review demo delivery**. Each group's all-time viewer-link row should show one arrival and one completion.
6. Choose **Recommend next test** and show **Wait for delivery evidence**.

The video and voice samples are bundled original demo material with local synthetic speech. The tagged links in this section mark their visits as rehearsals. The all-time link counters include those visits.

## Review delivery and prepare an experiment

Stop the server with Control-C and restart it on the same ports with the same database.

```sh
env -i PATH="$PATH" python3 -B scripts/placement_review.py serve --portable-demo propose --draft-db "$demo_dir/portable.sqlite3"
```

1. Open the new private planner link and return to **Campaign**.
2. Choose **Review demo delivery**, then **Recommend next test**. Show the editing group's authored window of four arrivals and one completion, beside the retained all-time link count of one arrival and one completion. The recommendation is **Test a shorter second take**.
3. Send **Review demo delivery** in the conversation. Show **Review demo delivery**, **0 model turns**, and the authored-fixture provenance in Agent activity.
4. To provide the local observation needed for the separate **Performance review**, open the approved editing group's **Open comparison** URL in three fresh tabs. Close each tab after it loads, without completing its takes. This creates three eligible local visits with zero completions. The earlier tagged rehearsals remain separate.
5. In **Performance review**, keep **Both creatives delivered** selected and choose **Review performance**. Show its separate sample-delivery and local-activity sections.
6. Choose **Keep both takes unchanged** and save the buyer correction. Run **Review performance** again to apply the correction, then choose **Prepare next test**.
7. Show the original and proposed instructions. Approve the new package. In **Run and review the instruction test**, allow one extra batch and choose **Run instruction test**, then **Save evidence snapshot**.
8. Show **Wait for the initial review point**. The empty experiment has zero eligible participant outcomes.

This section connects the screens through the normal browser commands. The delivery recommendation and the performance review retain their own evidence records. The instruction experiment begins after the corrected performance review and its approved draft.

## Prepare the authored learning example

Stop the server. Generate the report and a separate new database for the learning section.

```sh
env -i PATH="$PATH" python3 -B scripts/compare_instruction_policies.py \
  --output "$demo_dir/comparison.md" \
  --json "$demo_dir/comparison.json" \
  --walkthrough-db "$demo_dir/learning.sqlite3"
env -i PATH="$PATH" python3 -B scripts/placement_review.py serve \
  --portable-demo propose --draft-db "$demo_dir/learning.sqlite3"
```

The setup command creates a complete application example with authored participant outcomes of 2/20 for the original wording and 18/20 for the revised wording. It saves the finding, reopens SQLite and prepares an unapproved wording draft. The database path must be new on each setup run.

Use a fresh browser session for this database so saved conversation references from the portable example stay in their original session.

1. Open **Campaign**. Show **Wording from a saved finding**, its participant counts, estimated lift, probability and **Evidence source** disclosure.
2. Open **Start a fresh brief**, enter a title and goal, choose **Video editing**, and choose **Create brief**.
3. Show **Reuse tested wording** with the source experiment, snapshot and policy version. The fresh brief matches the context, recordings and baseline wording.
4. Stop and restart the same server command with the learning database. Open the newly printed private planner link and return to the fresh brief.
5. Choose **Prepare wording draft**. Show the proposed wording and the **Approve package** control. This new revision requires buyer approval.

The offline tests also exercise changed evidence, superseded and retired findings, mismatched context, media and brand, changed rules and corrections, and missing draft permission. The write command rechecks these conditions in the draft transaction.

## Present the comparison

Open the generated report or the [committed comparison report](instruction-policy-comparison.md). Show the frozen rules, aggregate table and paired examples.

- Across 312 paired simulations, the Bayesian policy wins 69 times, the fixed-lift baseline wins 55 times and 188 tie on net decision value.
- The Bayesian policy makes five mistaken reuse decisions and the fixed-lift baseline makes 44. The fixed rule reuses more worthwhile effects.
- The mean values are −0.0244 and −1.0564 under the declared utility and scenario mix. Keeping without collection earns zero in this scoring system.
- The existing assessment retains its native actions and per-arm visit minimum. Its actions are reported separately from the reuse/keep utility comparison.

End with the source-backed draft awaiting review. The demonstrated outcome is a reproducible workflow for learning and buyer decisions. The actual effect on campaign viewers belongs to a later authorized pilot.
