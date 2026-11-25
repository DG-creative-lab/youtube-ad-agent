"""Shared campaign capability and command binding values."""
import hashlib
import json

from .scope import BrandScope, Operator, WorkspaceContext


LOCAL_BRAND = BrandScope("local-client", "tts-demo")
LOCAL_OPERATOR = Operator("local-operator", frozenset({LOCAL_BRAND}))


LOCAL_CONTEXT = WorkspaceContext(LOCAL_BRAND, "local-workspace", "youtube-local")
CAPABILITIES = frozenset({
    "youtube:campaign.read", "youtube:campaign.draft", "youtube:campaign.approve",
    "youtube:campaign.export", "youtube:workspace.configure", "youtube:catalog.write",
    "youtube:setup.manage", "youtube:agent.run", "youtube:review.write", "youtube:learning.manage",
})


def command_hash(command):
    return 'sha256:' + hashlib.sha256(json.dumps(command, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()
