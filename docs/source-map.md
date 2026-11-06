# Source-code map

This map translates the [application architecture](architecture-plan.md) into code ownership. It describes the first slice as submitted in PR #2 and proposes where the next slices should live.

## Current checkout

| Path | What it owns today |
| --- | --- |
| [placement-review/index.html](../placement-review/index.html) | Placement search and review UI, unsaved selections, draft conflict reconciliation and per-context export. |
| [scripts/placement_review.py](../scripts/placement_review.py) | The local server and developer CLI. It also contains YouTube search, sample search, catalog classification and the optional Jev call. |
| [scripts/campaign_drafts.py](../scripts/campaign_drafts.py) | Seed brief and rules, catalog registration, draft validation, revision checks and SQLite transactions. |
| [tests/](../tests/) and [examples/](../examples/) | Offline behavior tests, authored catalogs and synthetic evidence. Private state and credentials live under the ignored `.local/` directory. |

Today the browser calls the loopback API, which delegates draft reads and saves to `CampaignDrafts`. The CLI also uses it to register independently supplied catalog entries. Live YouTube search results stay in the browser session. SQLite retains operator-declared catalog provenance and exact draft snapshots.

## Where the code should grow

```text
campaign_agent/              Python application package
  bootstrap.py               Wire concrete adapters when assembly needs a home
  http.py                    Translate browser requests to application commands
  access.py                  Resolve actor and client/brand scope, enforce grants
  campaigns.py               Brief references, drafts, review and handoff
  placements.py              Search and independent catalog assignment
  creatives.py               Creative versions and comparison examples
  measurement.py             Viewer events, completion and delivery evidence
  knowledge.py               Versioned briefs, brand rules and source permissions
  learning.py                Scoped preferences, findings and experiment proposals
  agent/                     Run lifecycle, mandates and typed tool dispatch
  adapters/                  Concrete storage, provider and runtime integrations
web/
  viewer/                    Plain HTML, CSS and JavaScript comparison experience
  planner/                   React and TypeScript when the fuller planner lands
scripts/                     Developer commands and research probes
tests/                       Offline tests organized by the behavior they protect
examples/                    Shareable fixtures and permitted example assets
```

These are proposed homes. Create a file or subpackage when a slice gives it real code and a caller. Keep a capability in one module until it has a concrete reason to split. For example, extract brand knowledge when briefs and rules need their own lifecycle. Add learning when a review can produce reusable findings. Add an agent module when the workflow needs a dispatcher and durable runs. Add separate activation and reporting integrations as their callers arrive.

## Dependency and ownership rules

- **Clients call commands.** The browser calls HTTP. Agent tools and developer commands call the same application commands for shared behavior. Request handlers and tool schemas translate inputs. The owning module validates scope, provenance, revisions and permissions.
- **Access is resolved at entry.** The backend resolves the actor and requested client and brand before loading private records. Tools inherit scope from the saved run. Public viewer routes resolve only the example and event scope assigned to the link. [Tenancy and growth plan](tenancy.md)
- **The caller owns the port.** Define a narrow interface beside the capability that needs it when the first integration warrants one. Concrete adapters implement those interfaces and own SQL, API mapping, credentials and provider-specific retries. Wire them at the entry point or in `bootstrap.py` once there is shared assembly.
- **State has one writer.** Each module owns its records and the transaction that protects them. Other modules use that module's commands or read contracts. One SQLite database is enough. Campaign revisions, viewer events, platform reports and learning findings have distinct identities and provenance.
- **Orchestration stays outside product rules.** A runner can ask the application to prepare a draft or analyze a report. Its session history and tool results carry no approval authority. The application checks the current grant and approved revision before any later provider write.

## Next slice

1. Introduce the seeded client and brand scope before the first durable viewer events. Put the comparison page in `web/viewer/` and serve it through the existing local server. Keep the placement page and both developer commands in place during this slice.
2. Give creative versions and comparison examples a small Python module. Resolve the exact example server-side from the CTA reference. Preserve the original creative reference separately if the viewer switches examples.
3. Put event validation, deduplication and completion in measurement code. Store events in SQLite with their own records. The viewer route calls that command and the placement draft keeps its existing write path. Extract HTTP or SQLite wiring when the two paths share enough implementation to justify it.
4. Verify both viewer variants, replayed event IDs and a missing sample through the owning commands and the browser. Keep the existing placement, draft revision, conflict and export behavior covered as the structure evolves.

Move existing files in small changes when a feature needs their boundary. Preserve the documented CLI, browser API and existing SQLite drafts during extraction. Start with import and ownership checks during review. Introduce an automated architecture check when a concrete dependency rule needs enforcement.
