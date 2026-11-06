# Security boundary checks

- Trace the input from the user, catalog, model, tool result or saved memory to the exact data store, render path or external effect. Identify who supplied it, whose authority the application uses and what protects the target. A plausible instruction embedded in data matters when it can change a real action or cross an access boundary.
- Verify workspace and campaign scope on reads and writes. For a provider effect, check the target account, exact package revision, action, cost limit and current grant at dispatch. Try a same-shape substitution or an edit between approval and dispatch. A rejected request should reach zero provider calls.
- Check that a delegated worker receives only its assignment's tools and data. Follow credentials through configuration, adapter calls, errors, logs and exports. Keep credentials out of prompts and worker results. Check that a saved preference or hypothesis can guide a proposal only within its scope.
- Use authored fixtures and fake adapters for local verification. Separate any live or deployment-dependent check and record what remains unknown.

[Cloudflare security audit skill](https://github.com/cloudflare/security-audit-skill/blob/main/skills/security-audit/SKILL.md) · [AI and LLM checks](https://github.com/cloudflare/security-audit-skill/blob/main/skills/security-audit/AI-AND-LLM.md)
