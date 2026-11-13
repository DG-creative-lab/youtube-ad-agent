"""Explicit local demo access; never a hosted authentication fallback."""
from campaign_agent.access import CAPABILITIES, LOCAL_CONTEXT


class LocalDemoAccess:
    def decide(self, request):
        expected = LOCAL_CONTEXT
        return "allow" if (
            (request.client_id, request.brand_id, request.workspace_id, request.installation_id) ==
            (expected.scope.client_id, expected.scope.brand_id, expected.workspace_id, expected.installation_id)
            and request.capability in CAPABILITIES
        ) else "deny"
