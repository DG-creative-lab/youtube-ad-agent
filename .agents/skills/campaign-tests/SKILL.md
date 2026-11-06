---
name: campaign-tests
description: Choose, write, review or prune tests for the YouTube campaign agent, with emphasis on meaningful regressions at state, authority and provider boundaries.
---

# Campaign tests

For each proposed case, name the regression it would catch, the observable failure, and the cheapest test layer that preserves the relevant boundary. Extend an existing case or use a table of related inputs when the setup and behavior are shared. Add coverage for requested cases and material gaps. Skip duplicate happy paths, private call-order assertions and tests that exist only to raise coverage. Before removing a test, identify retained coverage for the same failure, including any distinctive timing or data shape.

| Boundary | Test at this layer |
| --- | --- |
| Campaign state or approval | Use the real command and a temporary SQLite database. Assert the persisted revision, approval or step outcome. Reopen the database when restart behavior matters. |
| Provider or agent tools | Use the real dispatcher and a fake external adapter. Assert the exact target and action for an accepted effect, or zero provider calls on denial. Substitute a valid wrong scope, superseded revision, or late worker result when relevant. |
| Viewer path or export | Drive the affected route for behavior that depends on the browser. Check the saved event or exported data as well as the screen. Reserve browser checks for behavior that needs the browser. |
| Reporting and learning | Use authored inputs with independently known outcomes. Check evidence scope, denominator and provenance. Cover a partial report or a source with missing data where it changes the next decision. |

Keep expectations independent of the code under test. Use fixed fixtures, explicit expected outcomes or an invariant derived from the product contract. Mock only at the needed boundary. Use the existing `unittest` suite and temporary resources before adding test infrastructure. For a reproducible bug, demonstrate the regression check fails for the expected reason before the fix when practical. Run the focused case, then the [offline suite](../../../docs/engineering-workflow.md#verification). Track live verification separately.
