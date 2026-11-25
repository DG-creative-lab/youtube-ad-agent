"""Original command permits validated against the selected unit's owner/preimage."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from copy import deepcopy
from typing import Protocol

from campaign_agent.access import command_hash
from campaign_agent.ports.access import AccessRequest, AccessUnavailable, CommandPermit
from campaign_agent.ports.drafts import DraftRepository
from campaign_agent.ports.planner_context import CapturedComparisonMedia


class PlacementAuthority(Protocol):
    def decide(self, request: AccessRequest) -> str: ...
    def issue(self, request: AccessRequest, command: dict, session_digest: str,
              expires_at: float) -> CommandPermit: ...


@dataclass
class PlacementCommandState:
    command: dict = field(default_factory=dict)
    permits: dict[str, CommandPermit] = field(default_factory=dict)
    repository: DraftRepository | None = None
    postimage: tuple[str, str] | None = None
    media: CapturedComparisonMedia | None = None


class PlacementCommandScope(Protocol):
    def get(self) -> PlacementCommandState: ...
    def set(self, state: PlacementCommandState) -> None: ...


class PlacementAccess:
    def __init__(self, authority: PlacementAuthority, context, actor_id, campaign_id, *,
                 clock, monotonic_clock, command_scope: PlacementCommandScope, session_digest='local-placement', local_validate=lambda: None):
        self.authority, self.context = authority, context
        self.actor_id, self.campaign_id = actor_id, campaign_id
        self.clock, self.monotonic = clock, monotonic_clock
        self.session_digest, self.local_validate = session_digest, local_validate
        self.expires_at = None
        self.request_command = None
        self._state = command_scope


    command = property(lambda s: s._state.get().command, lambda s, v: setattr(s._state.get(), 'command', v))
    permits = property(lambda s: s._state.get().permits, lambda s, v: setattr(s._state.get(), 'permits', v))
    _repository = property(lambda s: s._state.get().repository, lambda s, v: setattr(s._state.get(), 'repository', v))
    _postimage = property(lambda s: s._state.get().postimage, lambda s, v: setattr(s._state.get(), 'postimage', v))
    media = property(lambda s: s._state.get().media, lambda s, v: setattr(s._state.get(), 'media', v))

    def _request(self, capability):
        c = self.context
        return AccessRequest(self.actor_id, c.scope.client_id, c.scope.brand_id,
                             c.workspace_id, c.installation_id, capability, self.campaign_id)

    def refresh(self, command, *, required=('youtube:campaign.read',)):
        if self._repository is not None:
            raise RuntimeError('A command decision cannot refresh inside a transaction.')
        self._state.set(PlacementCommandState())
        self.command = deepcopy({"request": self.request_command, "phase": command} if self.request_command is not None else command)
        self.local_validate()
        permits = {}
        for capability in ('youtube:campaign.read', 'youtube:agent.run',
                           'youtube:campaign.draft', 'youtube:catalog.write'):
            request = self._request(capability)
            try:
                permits[capability] = self.authority.issue(request, self.command, self.session_digest,
                                                          self.expires_at if self.expires_at is not None else self.clock() + 3600)
            except PermissionError:
                if capability in required:
                    raise
        self.permits = permits

    @contextmanager
    def bind(self, repository):
        if self._repository is not None:
            raise RuntimeError('Nested placement authority units are unavailable.')
        self._repository, self._postimage = repository, None
        try:
            yield
        finally:
            self._repository, self._postimage = None, None

    def _check(self, permit, request, *, allow_transition=False):
        if (not isinstance(permit, CommandPermit) or permit.request != request
                or permit.command_hash != command_hash(self.command)
                or permit.staff_session_digest != self.session_digest):
            raise PermissionError('The command binding changed.')
        if self.monotonic() >= permit.valid_until or self.clock() >= permit.wall_expires_at:
            raise AccessUnavailable('The command decision expired.')
        owner = self._repository.owner_row(request.campaign_id)
        expected = (request.client_id, request.brand_id, request.workspace_id, request.installation_id)
        if owner != expected:
            raise PermissionError('The native campaign changed.')
        row = self._repository.latest_revision_row(request.campaign_id)
        if row is None:
            raise PermissionError('The native campaign changed.')
        revision, snapshot = row
        import json
        draft = json.loads(snapshot)
        facts = (str(revision), command_hash(draft))
        preimage = (permit.campaign_revision, permit.native_snapshot_hash)
        if facts != preimage and not (allow_transition and facts == self._postimage):
            raise PermissionError('The native campaign changed.')
        if self.monotonic() >= permit.valid_until or self.clock() >= permit.wall_expires_at:
            raise AccessUnavailable('The command decision expired during native verification.')

    def decide(self, request):
        self.local_validate()
        if self._repository is None:
            return self.authority.decide(request)
        permit = self.permits.get(request.capability)
        if permit is None:
            return 'deny'
        self._check(permit, request, allow_transition=True)
        return 'allow'

    def transition(self, draft):
        permit = self.permits.get('youtube:campaign.draft')
        if permit is None or draft['revision'] != int(permit.campaign_revision) + 1:
            raise PermissionError('The draft transition was not authorized.')
        self._postimage = (str(draft['revision']), command_hash(draft))

    def before_commit(self):
        self.local_validate()
        for capability, permit in self.permits.items():
            self._check(permit, self._request(capability), allow_transition=True)
