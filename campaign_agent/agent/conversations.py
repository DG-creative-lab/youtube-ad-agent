"""Campaign-scoped buyer/agent transcripts; messages confer no execution authority."""
import json

from campaign_agent.ports.conversations import ConversationRepository, ConversationStorage
from campaign_agent.domain.errors import PackageConflict
from .replies import verified_result

MAX_CONTEXT_MESSAGES = 20
MAX_CONTEXT_BYTES = 8_000


def bounded_context(messages):
    """Keep a whole-message suffix, accounting for JSON nested in the provider's JSON body."""
    kept = []
    for saved in reversed(messages):
        # Transcript inspectors retain full evidence; dialogue carries its reference and reloads current facts through tools.
        message = {key: value for key, value in saved.items() if key not in {'review', 'experiment_review'}}
        if message.pop('delivery_report_id', None):
            message['content'] = 'A campaign delivery review was saved in the workspace.'
        for evidence in ('review', 'experiment_review'):
            if saved.get(evidence):
                message[evidence + '_id'] = saved[evidence]['id']
        candidate = [message, *kept]
        if len(json.dumps(json.dumps(candidate)).encode()) > MAX_CONTEXT_BYTES:
            break
        kept = candidate
    return kept


class CampaignConversations:
    def __init__(self, planner):
        self.planner = planner
        self.path, self.operator = planner.path, planner.owner.operator
        self.storage: ConversationStorage = planner.conversation_storage
        with self.storage.initialize() as store:
            for run_id, session_id, snapshot, outcome, status in store.legacy_transcripts():
                source = json.loads(snapshot)
                self.append(store, session_id, run_id, 'user', source['request'], source['revision'], source['catalog_id'], 'request')
                if outcome:
                    self.finish(store, run_id, json.loads(outcome), status)

    def session(self, store: ConversationRepository, session_id):
        self.planner.drafts.require("youtube:campaign.read")
        row = store.session_row(session_id)
        if row is None:
            return None
        if row[:3] != (self.planner.drafts.scope.client_id, self.planner.drafts.scope.brand_id, self.operator.id) or row[4] != self.planner.drafts.campaign_id:
            raise PermissionError('Conversation unavailable in this campaign.')
        return json.loads(row[3])

    def messages(self, store: ConversationRepository, session_id, limit=None):
        rows = store.message_rows(session_id, limit or -1)
        keys = ('id', 'role', 'content', 'run_id', 'revision', 'catalog_id', 'kind', 'created_at')
        messages = []
        for row in reversed(rows):
            message = dict(zip(keys, row[:8]))
            if message['role'] == 'assistant':
                result = verified_result(json.loads(row[8] or '{}'), message['kind'])
                if message['kind'] in {'answered', 'needs_input'}:
                    message['content'] = result['message']
                    if result.get('needs_verification'):
                        message['kind'] = 'needs_verification'
                if result.get('reply_version') == 1 and not result.get('needs_verification'):
                    if result.get('delivery_report_id'):
                        message['delivery_report_id'] = result['delivery_report_id']
                    for source, field in (('performance_review', 'review'), ('experiment_review', 'experiment_review')):
                        if result.get(source):
                            message[field] = result[source]
                            message['review_needs_refresh'] = result.get('review_needs_refresh', False)
            messages.append(message)
        return messages

    def append(self, store: ConversationRepository, session_id, run_id, role, content, revision, catalog_id, kind):
        store.append_message(session_id, run_id, role, content, revision, catalog_id, kind)

    def finish(self, store: ConversationRepository, run_id, result, kind):
        session_id, snapshot = store.job_context_row(run_id)
        source = json.loads(snapshot)
        self.append(store, session_id, run_id, 'assistant', result.get('message') or 'Request completed.',
                    result.get('revision', source['revision']), source['catalog_id'], kind)

    def begin(self, store: ConversationRepository, session_id, settings, run_id, request, catalog_id, revision, after_message):
        saved_settings = self.session(store, session_id)
        if (saved_settings is not None and
                {key: value for key, value in saved_settings.items() if key != 'prompt_version'} !=
                {key: value for key, value in settings.items() if key != 'prompt_version'}):
            raise PermissionError('Start a new conversation to change its model.')
        latest = store.latest_message_id(session_id)
        if after_message is not None and after_message != latest:
            raise PackageConflict('The conversation changed. Read the latest messages before sending your follow-up.')
        # A deliberate follow-up supersedes unfinished work. Late receipts cannot commit a tool result.
        for previous in store.running_runs(session_id):
            outcome = {'revision': revision, 'ambiguous': [], 'message': 'This unfinished request was superseded by your follow-up.'}
            store.supersede(previous, json.dumps(outcome))
            self.finish(store, previous, outcome, 'superseded')
        memory = bounded_context(self.messages(store, session_id, limit=MAX_CONTEXT_MESSAGES))
        count = store.message_count(session_id)
        store.create_session(session_id, self.planner.drafts.scope.client_id, self.planner.drafts.scope.brand_id,
                             self.operator.id, json.dumps(settings), self.planner.drafts.campaign_id)
        store.update_settings(session_id, json.dumps(settings))
        self.append(store, session_id, run_id, 'user', request, revision, catalog_id, 'request')
        return memory, count > len(memory)

    def read(self, session_id):
        with self.storage.read() as store:
            settings = self.session(store, session_id)
            if settings is None:
                raise LookupError('Conversation unavailable.')
            messages = self.messages(store, session_id)
            return {'id': session_id, 'campaign_id': self.planner.drafts.campaign_id, 'settings': settings,
                    'messages': messages, 'latest_message': messages[-1]['id'] if messages else 0,
                    'latest_run_id': messages[-1]['run_id'] if messages else None}

    def list(self):
        self.planner.drafts.require("youtube:campaign.read")
        with self.storage.read() as store:
            return [{'id': key, 'model': json.loads(settings)['model'], 'title': title[:80]}
                    for key, settings, title in store.list_rows(
                        self.planner.drafts.scope.client_id, self.planner.drafts.scope.brand_id,
                        self.operator.id, self.planner.drafts.campaign_id)
                    if title]
