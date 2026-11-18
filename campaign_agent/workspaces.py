"""Trusted provisioning policy for immutable campaign ownership."""
from .access import LOCAL_CONTEXT, require_access
from .ports.workspaces import WorkspaceStorage


def provision_workspace(storage: WorkspaceStorage, context, campaign_id, *, operator, access):
    """Provision product ownership using the trusted local provisioning policy."""
    if not isinstance(campaign_id, str) or not campaign_id.strip() or len(campaign_id) > 200:
        raise ValueError("Use a bounded campaign identity.")
    if campaign_id in {"tts-sample", "tts-catalog"} and context != LOCAL_CONTEXT:
        raise PermissionError("Demo campaign identities belong to the explicit local workspace.")
    require_access(operator, context, access, "youtube:workspace.configure", campaign_id)
    with storage.write() as unit:
        if unit.has_unowned_history(campaign_id):
            raise PermissionError("Legacy campaign ownership needs explicit reconciliation.")
        # Recheck the trusted local policy after acquiring the writer reservation.
        require_access(operator, context, access, "youtube:workspace.configure", campaign_id)
        unit.bind(context, campaign_id)
        unit.commit()
