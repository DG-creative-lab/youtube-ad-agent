# Gateplane wire v1 source

`gateplane-v1.json` is the producer's public schema from
[accepted M0 revision d8eb4f4](https://github.com/DG-creative-lab/agentic-auth/blob/d8eb4f4073753573fc809a557521e4428719ea1d/contracts/access/v1/schema.json).
Producer Git blob: `9bfc7650019f5fe9cb852cbcba088557e01366fd`.
The [acceptance record](https://github.com/DG-creative-lab/agentic-auth/blob/d8eb4f4073753573fc809a557521e4428719ea1d/docs/architecture/m0-contract-acceptance.md)
accepts the bounded wire/reference profile while retaining real service and
consumer activation gates. Historical producer artifact titles still say
“Proposed”; this copy does not change the schema or claim service conformance.

The product validates PrincipalContext, DecisionRequest and DecisionResult
against these definitions. Other definitions are retained unchanged so internal
references and the producer artifact remain identifiable. No Gateplane ORM,
implementation or private SDK source is imported. The fixture authority creates
synthetic records against the same schema; it verifies consumer behavior, not
Gateplane or real issuer behavior.

Product input profile `youtube-command-v1` is UTF-8 JSON with sorted object keys,
`,` / `:` separators, literal Unicode, finite numbers only and no duplicate
object/query keys. It hashes the method, path, parsed query and declared command
body. Subject profile `youtube-subject-v1` binds actor, native campaign target,
client/brand/workspace/installation, capability, requested effect, input hash,
current revision and a digest of its persisted snapshot. These are product-owned
profiles for offline owner review; they are not production registration approval.

Runtime transport is an injected `context` / `decide` client facade, not a new
public Gateplane protocol. Replace it with the accepted private client when #81
is available, with a separately registered control credential and real verified
subject evidence. No network transport or custom token verifier is bundled here.
