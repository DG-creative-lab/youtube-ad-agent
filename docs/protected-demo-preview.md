# Protected contextual YouTube demo

This preview runs the portable React planner and Python campaign commands over HTTPS with fictional video editing and audiobook contexts. The simulator, placement catalogue, viewer media, setup and delivery fixtures are the authored offline configuration. The preview blocks provider credential headers, provider connection routes and uploads through catalog import.

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
