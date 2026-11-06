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
| Signature | Use the nested rounded squares as the provisional reference for a small, static workspace mark. Keep the product name and final logo open. Check redistribution rights before adding any source asset to the public repo. |

Use flat sections, aligned columns and generous separation between decisions. Keep optical geometry at identity scale and the work surfaces solid. Let the original clip or passage provide the viewer's visual focus. The public project can use system typography and plain text identity while any asset provenance is resolved. Present ElevenLabs as the campaign example and preserve platform attribution where it appears.

## Two surfaces

**Planner.** The working brief, placement list, package or review occupies the main column. The fuller planner has a compact black navigation rail for saved campaigns. The agent shows the next decision in the main workspace, with sources and run history available in a secondary inspector. Use flat, scannable placement rows. On package review, place the exact cut, destination, targeting and revision together. Use action labels such as **Approve package** and **Export setup** that describe the actual effect. At narrow widths, put the decision first and make navigation and evidence available on demand.

**Viewer comparison.** Use a single warm-paper column with the clip or passage at the top. Keep the media area stable as the viewer switches takes. Label both playback controls and make **Choose this take** easy to find. Use the same typographic and action treatment as the planner, with a compact identity line. Show captions or passage text and keep playback deliberate. Stack controls on narrow screens when needed.

## First application and review

Apply the visual foundations to the placement workspace and comparison page as those slices are built. Keep palette, type and focus in shared CSS variables so the React planner can use them later. Review the actual content at desktop and narrow widths. Check visible keyboard focus, at least 44px primary interaction targets, long titles, local table overflow, unavailable media and explicit labels for sample, replayed and observed evidence. The first visual review should show the planner's package decision and both comparison variants with representative content.
