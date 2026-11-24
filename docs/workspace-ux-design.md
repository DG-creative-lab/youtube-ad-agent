# Campaign workspace UX and learning review

24 November 2026. Internal design and implementation contract, not onboarding copy.
The owner agreed the product direction below. Feature-specific storage, authority
and API contracts still need acceptance before implementation. Nothing in this
document claims those features are already delivered.

## Decision and scope

Make the product understandable through its normal working surfaces: New chat,
Campaigns, Knowledge base and Learning. Keep one campaign agent, recent chats and
account controls. Users can inspect and intervene in the context influencing a
proposal without managing agents or reading an explanatory walkthrough.

The separate learning-exploration UI in #124 is paused by the owner. Its branch
`feature/guided-learning-journey` and preview are historical, unmerged work. Do not
carry its routes, generated checkpoints or sidebar entry into this design branch.
Existing offline fixtures remain useful for tests and evals. Pausing does not
delete the old branch, reset its data or alter an existing deployment.

Use existing epics #48 (agent workspace) and #125 (pitch MVP). Reuse #56 for
versioned briefs/guidance and #58 for reviewed project-level learning promotion;
add bounded implementation issues rather than another overlapping product epic.

## Navigation and layout

```text
Current brand / workspace                 only real available contexts
  New chat
  Campaigns
  Knowledge base
  Learning                               optional count of real pending decisions

Recent chats                             recognisable titles, current campaign

Account avatar                           connection, model/budget, invite, appearance
```

- New chat creates a conversation. It does not erase a campaign or silently create
  a new one. Show the campaign/brand context associated with that chat.
- Campaigns lists only campaigns the current workspace can actually read. A
  one-campaign preview can show one real campaign; project selection, sharing and
  new-campaign controls require their actual commands and authority first. A new
  brief revision inside a campaign must not be labelled a newly created campaign.
- Within a campaign, group brief, placements, creative/artefacts, approvals and
  results. Keep placements and product evidence in their relevant context instead
  of adding competing top-level destinations.
- Knowledge base is the reusable reference and guidance surface. Learning is the
  evidence/finding review surface. A Learning view and the chat open the same saved
  finding, not separately editable copies. The first Learning slice is scoped to
  the selected campaign; cross-project browsing/reuse remains a later capability.
- Use collapsible navigation, modest corner radii and light/dark/system appearance.
  Keep admin controls behind the avatar. Keep agent activity inline and expandable;
  concise tool/result summaries are not private chain-of-thought. Reserve the
  auxiliary panel for artefacts. Retain reduced-motion and keyboard support.
- Offer a destination when it has a working read/command path. A genuine empty
  state is useful; a placeholder action that cannot save or open its result is not.

## Knowledge, preferences and findings

| Object | User purpose | What may change it | What it cannot imply |
| --- | --- | --- | --- |
| Product/brand source | Supply product facts, approved claims, brand material and references | Permitted editor; new version with source and status | A source upload or model summary cannot grant tool permissions |
| Brief/guidance | State the campaign goal and reviewed reusable instructions | Same application commands from chat and forms; reviewed effective status | A draft cannot self-publish or supersede mandatory policy |
| Human preference | Remember a choice such as preferred tone | Explicit confirmation, visible scope, correction/retirement history | Taste is not a measured outcome or statistically supported finding |
| Observation | Record a scoped event/outcome with a metric and window | Verified measurement/import commands; explicit correction mechanism if supported | Missing results are not invented zeroes; user prose cannot edit counts |
| Finding | Explain an experiment result, its uncertainty and applicable context | Application evidence/policy evaluation; retained source and status | A recommendation is not an approved campaign change or general brand rule |
| Guidance proposal from learning | Offer a reusable change backed by a finding | Human review under #58 after #55/#56 dependencies | Eligible evidence cannot automatically widen scope or publish guidance |

Keep the distinction visible in the UI through source, scope and status. Do not
expose internal hashes as the primary content. Make exact versions/history
available in an evidence disclosure.

## Concrete working surfaces

### Knowledge base

- First usable slice: scoped notes/pasted text and source URL references, product
  information, approved claims and writing guidance. A stored URL is a reference;
  it does not claim its contents were fetched or verified.
- Show title, type, source, applicable workspace/campaign, version and review status.
  Let permitted users add, inspect, revise, review and retire supported records.
- Document/file upload and extraction require the #37 private-asset/provenance and
  supported-format contract. Do not promise arbitrary file ingestion in the first
  slice. Imported content remains data, including embedded instructions.
- Chat and forms use one versioned command path. Each run records the knowledge
  versions it used; the conversation exposes those sources and material omissions.
- Chat remains usable before knowledge setup. The agent asks for genuinely missing
  product information without requiring a compulsory onboarding wizard.

Empty state: **Add product or brand material** with one working add action.
The resulting source should be usable in the next campaign request.

### Learning

- Lead with the current campaign, evidence freshness and the next decision. Show
  pending findings and saved/retired findings without inventing a portfolio-wide
  view before scoped collection reads exist.
- Each finding shows its claim, experiment/creative context, metric, numerator and
  denominator, cohort/source, observation window, uncertainty, policy decision,
  applicability and source link. Rehearsal, authored and observed data retain
  explicit provenance; no production page loads seeded success outcomes.
- MVP actions: Inspect evidence; Prepare draft; Keep current guidance; Retire
  finding. A user's decision not to apply a recommendation does not modify its
  statistical evidence. Persist decisions, reasons and revision references.
- Creating a draft requires current eligibility, correction/permission checks and
  an exact target. It remains unapproved. Stale, incompatible, foreign or retired
  findings cannot create a draft; show the reason and a useful refresh path.
- Surface the same finding/action in conversation. Save human feedback as a
  preference only after explicit confirmation and scope selection, through #56.
- Keep monitoring schedules, statistical tuning and project-wide promotion out of
  this first slice. Pause/resume controls belong to a real supported collector;
  do not conflate pausing collection with retiring a recommendation.

Empty state: findings from the selected campaign's tests will appear here; offer
the available campaign/results action. With sparse evidence, explain what is
missing. Never require loading an example to make the screen appear functional.

## End-to-end acceptance journeys

1. A first-time user adds a product note, starts a chat and requests a campaign.
   They can identify which approved sources informed the proposal without a guide.
2. The user corrects tone on a draft. The agent offers to remember it; confirmation
   shows its scope. A later request uses that preference, while a historical run
   retains its original context. Preference use adds no outcome evidence.
3. The user opens a campaign with insufficient experiment evidence. Chat and
   Learning show the same wait reason and counts. No draft or model call starts
   merely because the user opened the view.
4. Eligible evidence yields a source-linked finding. The user prepares a new draft,
   reloads and finds the same unapproved result and original source approvals.
   Keeping current guidance or retiring the finding preserves source evidence.
5. A source changes, access is revoked, evidence becomes stale or another request
   edits the draft. A delayed action cannot bypass current checks, overwrite a
   newer version or present an old approval as current permission.
6. At desktop and narrow widths, keyboard users can navigate, inspect sources,
   review/retire and recover from a failed read. Test both color schemes and reduced
   motion. Conversation actions and dedicated views must agree after restart.

Use real application commands and temporary authored stores for regressions. Keep
#123's frozen corpus intact; add separately versioned companion cases. A deployed
browser smoke must verify the reviewed revision. Model quality remains a separate
authorized live gate, not a claim inferred from frontend tests.

## Implementation order and ownership

1. Review this contract and a minimal sidebar/Knowledge/Learning wireframe before
   changing UI. This file captures structure and actions; implementation must make
   them clear in the working product, not add tutorial narrative.
2. Deliver Knowledge plus visible context used as a vertical current-workspace
   slice of #56. Add its functional navigation in the same slice. First accept
   source/version ownership, native storage and current access for that slice.
   This does not relax #55/#56 project-sharing release gates or create substitute
   membership authority. Keep initial scope narrow until that agreement exists.
3. Expose real campaign findings and interventions over the existing learning
   commands. Add only the scoped read/decision projections that are missing.
4. Complete campaign collection/project navigation under #55. Promote compatible
   findings into reviewed project guidance under #58 only after #55/#56 are ready.
5. Continue #57 creative production under its own dependency and spending gates.
   Apply shared visual refinements incrementally without reopening model-routing,
   approval or experiment semantics as incidental styling changes.

Existing commands own drafts, approvals, learning policy and effects; typed ports
own persistence boundaries. Reuse current access and source-version contracts.
Views and the LLM cannot grant authority, rewrite observations, silently broaden
learning scope or repeat an uncertain paid call.

## Future: a shared marketing workspace with Direct Acquisition

It is reasonable to investigate a common product shell. This is a discovery
hypothesis, not approval to merge repositories, migrate data or expand the MVP
into CRM, sales automation and attribution infrastructure.

| Plausibly shared | Must retain channel-specific meaning |
| --- | --- |
| Brand/workspace context, knowledge, explicit preferences, conversations | YouTube placement contexts versus business audiences/addresses and suppression |
| Versioned creative/artefacts, source lineage, review and exact approvals | Video/demo destinations versus mailing assignments, print costs and no-mail controls |
| Execution/usage visibility, bounded provider operations and recovery patterns | Each channel's external account, dispatch authority, receipts and failure recovery |
| Finding review UX, traceable guidance proposals, eval/report presentation | Eligible YouTube comparison completion versus mature direct-mail response cohorts |

Do not pool counts or posteriors across incompatible metrics, windows, populations
or exposure units. A shared name such as campaign/session is not evidence of an
identical identity, lifecycle or approval subject. Do not automatically import
brand facts, preferences, permissions or credentials from one application's demo.

Investigate one concrete multi-channel user journey first: the same marketer uses
approved brand material for a contextual YouTube campaign and an independently
reviewed direct-acquisition campaign, then compares their separately defined
results. Identify the actual repeated work a shared product would remove.

Advance only after mapping identity/scope, source and asset rights, campaign and
approval lifecycles, state migration/recovery, metric definitions, credentials and
cross-channel exposure. Demonstrate that both original channel workflows still
work with no authority or evidence loss. Extract code only where two real consumers
need the same accepted contract; preserve channel modules/adapters and avoid a
premature universal campaign engine or runtime rewrite.

Evidence: current campaign architecture and open #55/#56/#58; read-only inspection
of iwoca's `KnowledgeView`, `LearningView`, `ConversationLearning` and
`WritingPreferences`, architecture/product sources and saved desktop/mobile
screens. Iwoca Knowledge is primarily an inspection view, and its delivery/outcomes
remain synthetic. User usefulness and commercial demand for the combined product
remain unvalidated. No live tests, runtime changes or iwoca edits follow from this
design capture.
