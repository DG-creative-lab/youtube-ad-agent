# Campaign agent design direction

6 November 2026 · Working direction for the independent application project. [Product brief](product-brief.md) · [Architecture](architecture-plan.md)

## Brand foundations

Use the DG Creative Lab publication identity as adapted for a working application. The Remotion Brand Studio establishes the palette and typography. The current Direct Acquisition branding guide shows the lighter application treatment with a black rail and quiet, dense work surfaces. The rebranded commerce workspace shows how the compact navigation, one visible next action and optional evidence inspector work together.

| Role | Direction |
| --- | --- |
| Main canvas | Warm paper `#faf9f6` with ink `#171717` and secondary text `#626262`. |
| Surfaces | Hairline rules `#deddd9`, quiet fills `#efeeeb` and white media or input surfaces where needed. |
| Navigation and actions | Black `#000000` with warm white `#f4f3ed` on dark surfaces. Use one prominent action for the current decision. |
| Typography | System Arial, Helvetica, sans-serif. Bold headings at weight 700 with tight tracking around `-.035em`. Use compact, readable type for planner rows and system monospace for technical identifiers. |
| Status | Pair every status with text. Reserve semantic colors for states such as success, warning and error. Keep provenance labels readable in monochrome. |
| Signature | Use the shared nested-square mark at navigation and favicon scale. Retain the DG Creative Lab product name. Preserve the mark's square proportions and keep it off work surfaces. |

Use flat sections, aligned columns and generous separation between decisions. Keep optical geometry at identity scale and the work surfaces solid. Let the original clip or passage provide the viewer's visual focus. Use the shared publication mark and system typography. Present ElevenLabs as the campaign example and preserve platform attribution where it appears.

## Two surfaces

**Planner.** The working brief, placement list, package or review occupies the main column. The fuller planner has a compact black navigation rail for saved campaigns. The agent shows the next decision in the main workspace, with sources and run history available in a secondary inspector. Use flat, scannable placement rows. On package review, place the exact cut, destination, targeting and revision together. Use action labels such as **Approve package** and **Export setup** that describe the actual effect. At narrow widths, put the decision first and make navigation and evidence available on demand.

**Viewer comparison.** Use a single warm-paper column with the clip or passage at the top. Keep the media area stable as the viewer switches takes. Label both playback controls and make **Choose this take** easy to find. Use the same typographic and action treatment as the planner, with a compact identity line. Show captions or passage text and keep playback deliberate. Stack controls on narrow screens when needed.

## First application and review

The chat composer is one square input surface with the model menu and send control inside its footer. Keep source selection, allowed changes and import behind small labelled outlined controls below it. The Changes control always shows the current request's permission, defaults to Review only and resets after sending. Reveal one options panel at a time, retain typed text when changing models, and keep model/specialist details in the model menu or activity inspector. Preserve visible offline/live provenance. Keep the conversation readable and the current campaign draft distinct from historical message revisions. Menus and panels support keyboard use, Escape and reduced motion.

Apply the visual foundations to the planner, placement workspace and comparison page. Keep palette, type and focus in shared CSS variables. Review the actual content at desktop and narrow widths. Check visible keyboard focus, at least 44px primary interaction targets, long titles, local table overflow, unavailable media and explicit labels for sample, replayed and observed evidence. Visual review should show the planner's package decision and both comparison variants with representative content.

## Shared application UI · 13 November 2026

The owner selected the sibling iwoca workspace as the application reference, including its logo. `web/brand/mark.svg` is copied unchanged from `iwoca/frontend/public/brand/nested-squares.svg`, whose branding guide records the owner-selected publication mark and its commerce-workspace source commit `add1d4228ee1307d3bab1af8ecb420339f8a7e71`. Asset SHA-256: `569cccffd1aaff1f43019162de16ea69977da795a45b1c91cee9a83d23779a5a`. This is the publication mark, not iwoca's corporate logo.

`web/brand/tokens.css` owns the common palette, system font, identity treatment and static-page navigation. The planner bundles those tokens; placement review and the public viewer load the same stylesheet. Both local origins serve exactly the two public brand files through `/brand/mark.svg` and `/brand/tokens.css`. These routes do not accept arbitrary filenames. Private API access continues through the existing operator and viewer checks.

Use a black staff rail, compact breadcrumb bar, flat campaign sections and square inputs, menus and actions. The rail becomes a wrapping top navigation on phones. Saved conversations, permitted draft changes and evidence provenance retain their existing behavior. The viewer keeps its single comparison column and media controls. UI consistency is the first enterprise preparation slice; hosted identity, tenancy, deployment and Gateplan integration remain separate work.

Placement review attaches the browser's leave-page warning while selections across either creative differ from the saved draft, a search or import is underway, or search results or imported proposals remain in page memory. Saving selections clears only the selection-related warning; remaining session work stays protected. Cancelling navigation or reload leaves that work in place. With no planner build, the server hides **New request** and **Campaign**, and shows the commands to enable them. Cross-page **New request** uses `/?new=1` to invoke the planner's existing conversation reset before restoration. The planner consumes that query flag so a reload retains the fresh conversation. Existing conversations remain available through the saved-conversation selector.

Verification used a fresh temporary SQLite database with the portable propose scenario and an empty provider environment. All 156 offline tests and the planner build passed. Chromium exercised package approval, simulated setup, both tagged rehearsal viewers, take switching and navigation between planner and placements. The planner, placements and both viewers fit at 1440px and 390px; campaign text also fit at 200% size at 1440px, 768px and 390px. Skip-link focus, menu Escape/focus restoration and reduced-motion behavior passed. Direct HTTP checks verified both brand files, rejected arbitrary brand paths and incorrect hosts, and retained private API denial without the operator token. These checks cover the local UI slice; they do not establish hosted enterprise readiness.

The navigation review reproduced both earlier failures in Chromium before the fixes. Follow-up checks cancelled Campaign, identity-link, New request and reload navigation with unsaved selections; verified that changing the visible creative did not hide another creative's edits; and confirmed no warning after saving. A request started from placements used a new conversation ID, `after_message: 0` and `draft_permission: none`. Reload retained that new conversation, and the previous transcript could still be reopened. All 156 offline tests and the planner build passed again.

The follow-up review checked search results and imported proposals without selected placements in the in-app browser. Attempted navigation retained the search results and all four authored proposals. Saving an imported selection still retained the proposals and protected them from navigation. An isolated source copy without a planner build served the standalone page at both `/` and `/placements`, with planner links hidden and build commands visible. Adding the planner build enabled both links and their destinations. These checks used local sample search and authored imports, with zero live-provider calls; all 156 offline tests and the planner build passed.
