# Tenancy and growth plan

The client organization owns the tenant. The Python application owns the rules for that tenant's data, people and provider actions. React and TypeScript provide the staff planner through the HTTP API. The public viewer page has its own narrow read and event path. [Architecture](architecture-plan.md) · [Source-code map](source-map.md)

## Ownership and access

| Entity | Ownership and access |
| --- | --- |
| Client tenant | Owns its brands, memberships and provider connections. A client administrator can grant access and revoke it. |
| User | A person may work for several clients through separate memberships. An agency user receives access from each client. |
| Brand | Belongs to one client tenant. Brand grants can limit actions such as editing briefs, preparing campaigns or reviewing results. A workspace selector shows the current client and brand. |
| Campaign and run | Belong to a brand. The package references exact brief, creative and policy revisions. A run has an initiating actor, scope and allowed capabilities. |
| Viewer link | Resolves server-side to a particular creative and comparison example. It permits access to that example and submission of its allowed viewer events. |

Authentication answers who is calling. Application authorization answers what that actor can do for this client, brand and resource. A requested tenant or brand ID selects a candidate scope. The backend checks membership and permission before using it. Every private read or write resolves the owning tenant, including access by revision, asset, report, catalog reference and provider connection. Store the ownership on the record or enforce it through its parent in the same query or transaction. Apply the same scope to retrieval, exports and background work.

## Agent and memory boundaries

- **The in-process Python loop** is the first runtime behind `AgentRuntime`. Use recorded model responses for the offline walkthrough. Borrow the Superagent pattern of scoped assignments and recorded outcomes as the workflow needs it.
- **The Python application** owns the typed tool dispatcher, registered capabilities, durable runs and approval records. Skills guide the agent's work. Each tool call is checked against the run's mandate, and children receive a subset of that mandate. Recheck current authority before a consequential effect, including after a retry or a membership change.
- **Brand knowledge** holds approved briefs, claims and rules by brand and revision. **Learning memory** holds evidence-linked hypotheses, findings and preferences with their own scope. The agent can use memory to propose the next test. Updates to approved knowledge follow the client's review rules. Retrieval begins within the client's authorized scope, including when the same person works for multiple clients.

## When to build each layer

| Stage | Build and verify |
| --- | --- |
| **POC, starting with the viewer slice** | Resolve a seeded local operator, tenant and brand on the backend. Keep SQLite and bind new durable viewer events to server-resolved example ownership. Preserve existing local drafts and catalog registrations in an explicit local scope when adding ownership to those tables. Test the lookup and write paths with two fixture clients and a brand-restricted operator. A valid resource ID from outside the allowed scope must fail. A viewer link must have no access to the planner's private records. |
| **Hosted MVP** | Add staff sign-in, client invitations and membership administration. Enforce tenant and brand permissions across the React planner, API, exports, agent runs and provider connections. Use a shared database and appropriate asset storage when deploying across multiple processes. Carry the same command and ownership contracts across adapters, and test revocation and concurrent writes in the hosted configuration. |
| **Enterprise, as clients require it** | Add capabilities such as enterprise sign-in, provisioning, audit export, retention controls and stronger data isolation. Split deployment components when measured workload or client isolation requirements justify it. Preserve the same application commands and tenant ownership rules. |

The current loopback build separates sample and catalog campaigns by mode. Those IDs describe demo data partitions. The next slice should establish the client and brand boundary before recording viewer activity, so future reporting, memory and agent runs inherit the correct owner from the start.
