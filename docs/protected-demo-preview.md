# Protected contextual YouTube demo

This preview runs the portable React planner and Python campaign commands over HTTPS with fictional video editing and audiobook contexts. The simulator, placement catalogue, viewer media, setup and delivery fixtures are the authored offline configuration. The live preview accepts a foreground OpenRouter connection through the sidebar account menu. Local runs still default to the offline demo. Catalog imports accept permitted user-supplied metadata.

## Reproduce the build

From the repository root with Node and Python available:

```sh
pnpm --dir web/planner install --frozen-lockfile
pnpm --dir web/planner build
python3 -m preview.build_seed
python3 -m preview.stage /tmp/contextual-youtube-preview
python3 -m unittest discover -s tests -p test_protected_preview.py -v
```

Use a Vercel project with Vercel Authentication on Preview and a separate Turso Starter database connected to **Preview**. Configure `DEMO_INVITES` as a Preview environment setting, using an object from SHA-256 digests of independently generated 32-byte URL-safe invite codes to UTC Unix expiry times. Share the original code only with its reviewer. This app serves only the unique Vercel deployment hostname, and its Vercel entrypoint refuses production requests. Deploy the staged directory as Preview and use the unique deployment URL. `/health` runs a fresh read-only Turso query with a two-second network timeout, reports the fixture label, and returns HTTP 503 when the probe fails.

The seed is generated from the tracked schema and catalogues. On each request the application loads the invite's own SQLite data into a fresh temporary file. After an offline write, Turso persists its compressed snapshot with a matching version condition. Conflicting writes return 409 and leave the newer workspace intact. The browser can reopen the saved run after refresh and after a new deployment against the same database and fixture version. Keep the target database, invite digests and fixture version fixed for a restart against existing workspaces.

## Review and reset

1. Open the protected preview URL, sign into Vercel, then enter the assigned demo code.
2. Choose **Try the offline example**, open the campaign, approve the package and export the JSON handoff.
3. Open an audiobook comparison, play both samples and save a choice. Reopen the campaign to inspect the saved draft and approval.
4. Manage an invite at `/invite`. **Reset workspace** clears only the current invite's demo data. **Disable invite** blocks that code across deployments connected to this same database. The invite expiry also applies across those deployments. To stop all access immediately, pause the dedicated Vercel project or revoke its deployment access.

The snapshot store is bounded to 4 MiB per SQLite workspace and 768 KiB compressed. This preview is intended for disposable authored campaigns and has a single-writer decision per invite. Enterprise persistence and real provider activation have separate release gates.

## Live model availability

The account menu owns the OpenRouter key, model, filters and local run budget.
Model metadata comes from OpenRouter, with the catalogue restricted to text-output
models advertising tools and tool choice. Multimodal models may be used for text
input. Catalogue prices are advisory; a selectable candidate receives a fresh
endpoint check when the buyer presses Use. There is no model allowlist.

A usable planner endpoint must advertise tools, required tool choice, an output
token cap and sufficient token/context limits. The app chooses the compatible
route with the lowest conservative per-call reservation, pins its provider tag,
prices, capabilities and one-hour qualification deadline, and revalidates before
new inference. A changed or missing route requires reselection; no fallback is
silently substituted. Account/provider restrictions can still reject a request.

Cache-read rates are retained. Reservations include a conservative all-input
cache-write allowance and never assume a cache hit. Optional media and web-search
prices do not block text requests because those provider features are not enabled.
Unknown, conditional or separately billed reasoning rates remain unsupported and
are explained in the model list when route selection fails. Keys remain only in
the current tab and request, with verifiers and immutable selections in storage.

## MVP run diagnostics

The campaign agent uses its own Python tool loop and application-owned authority,
receipts and replay controls. It does not currently use OpenAI Agents SDK or
Claude Agent SDK. The protected preview exposes a versioned, scoped diagnostic
projection from the existing inference journal: model/provider, call position,
execution and accounting states, HTTP status, error category, finish reason,
token counts, recorded duration, cost and provider request identifier when known.
Agent activity shows failures and uncertain outcomes separately from completed
work. Save diagnostic JSON exports only those metadata fields.

A separate logging database or in-memory session cache is unnecessary for this
slice. Function memory cannot provide reliable history across cold starts.
Conversation records and recovery receipts must remain durable across tab closes
and sign-out, including unknown calls and reservations; deleting them at session
end could cause repeated requests or lose accounting. Optional debug UI state is
in memory and clears with the view. The existing invite reset is the explicit
whole-workspace cleanup operation.

The diagnostic projection and export exclude prompts, replies, tool arguments,
credentials and private reasoning. Existing model tool receipts remain private
recovery records. Future eval curation should require a reviewed, redacted example
with the relevant permitted transcript, expected behavior and outcome; a metadata
trace alone cannot measure answer quality. Do not automatically promote live
customer conversations or failed model output into the authored eval corpus.

The SDKs provide useful tracing conventions, but adopting a new agent runtime
would require preserving the existing scope, approval, budget, receipt and replay
contracts. For now, keep this small trace contract and consider OpenTelemetry
export through an adapter when we need cross-service tracing or a hosted collector.
