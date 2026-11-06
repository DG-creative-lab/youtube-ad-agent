# Engineering workflow

## Design a slice before coding

1. Write the user outcome, normal entry point, state owner, and acceptance evidence in a short note. For a feature that changes durable state, name the records and when the update commits. For an external effect, name who can authorize it and how an uncertain result is reconciled.
2. Build the smallest slice that reaches a user-visible result. Exercise it before taking the next slice. Keep a speculative prototype separate and record the decision it helped make.
3. Review the diff against the acceptance evidence. Report what ran, the entry point exercised, and any behavior that still needs a browser, runtime, or provider check. Keep independent verification separate from the implementation's own assumptions. [pstack feature playbook](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/feature.md) · [pstack prototype playbook](https://github.com/cursor/plugins/blob/main/pstack/skills/poteto-mode/playbooks/prototype.md)

## Test where the behavior happens

Run `python3 -m unittest discover -s tests -v` locally and in CI. Tests use authored fixtures, temporary state, and fake adapters. The initial suite covers the placement baseline. Add the applicable checks below as each milestone introduces the behavior.

| Surface | Evidence to capture |
| --- | --- |
| Commands and persistence | Use the real command and temporary SQLite. Reopen after restart. Check a stale revision, duplicate request, or interrupted step against stored state. |
| Tool authority and effects | Enter through the real dispatcher with a fake provider. Assert the exact normalized call on success and zero provider calls on denial. Include a wrong workspace, changed approval target, or late result after cancellation where applicable. |
| Browser and media | Drive the relevant route from a clean session. Verify both demo variants, keyboard operation, and a degraded path. Capture desktop and narrow screenshots for visual changes. Check the resulting event or export where it is stored. |
| Agent decisions and learning | Replay fixed observations for low delivery, low completion, and missing evidence. Check that the next proposal cites the right scope and source. Treat a real model run and human-labelled assignment evaluation as separate evidence. |

For security review, trace untrusted input from its source to the specific capability, data store, render path, or provider call it could influence. Check the actor, target, exact action, and deterministic enforcement. Start with tool argument handling, approval binding, scope, memory provenance, and credential isolation. Reproduce consequential failures with a local fake. Record provider behavior that still needs validation. [Cloudflare audit skill](https://github.com/cloudflare/security-audit-skill/blob/main/skills/security-audit/SKILL.md) · [AI and LLM checks](https://github.com/cloudflare/security-audit-skill/blob/main/skills/security-audit/AI-AND-LLM.md)

## UI design rules

The planner is a working desk. Give the current brief, package, or review the main surface and keep evidence beside the decision it informs. The viewer page has one focal point, the clip or passage and its two takes. Use shared CSS variables for type, spacing, color, and focus when a second screen needs the same styles. Start with a neutral base and one action accent.

Use plain status labels alongside color. Show sample, replayed, and observed evidence where it appears. Design loading, empty, unavailable, and completed states alongside the main path. Preserve visible keyboard focus, label the playback and choice controls, and keep both viewer paths usable on narrow screens.
