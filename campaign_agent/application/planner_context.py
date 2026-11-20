"""Package identity and placement context policy over typed scoped facts."""
from copy import deepcopy
import json
from urllib.parse import urlencode

from campaign_agent.domain.fingerprints import package_fingerprint
from campaign_agent.domain.measurement import measurement_capabilities
from campaign_agent.ports.drafts import DraftRepository
from campaign_agent.ports.planner_context import ComparisonMedia, PlannerContextRepository

VIEWER_ATTRIBUTION = "campaign_comparison_content_v1"
CORRECTION_CHOICES = {
    'keep_takes': 'Keep both takes unchanged',
    'keep_comparison': 'Keep the entire comparison unchanged',
}


def comparison_identity(group, *, keep_takes=False):
    excluded = {'preview_sha256'}
    if keep_takes:
        excluded.add('instruction')
    content = {key: value for key, value in group['content'].items() if key not in excluded}
    return package_fingerprint({'comparison_version': group['comparison_version'], 'content': content})


def package_blockers(package):
    blockers = []
    for group in package['groups']:
        title = group['title']
        if not group['placements']:
            blockers.append(f'Add placements for {title}.')
        content = group['content']
        if not content['preview_sha256'] or any(not take['sha256'] for take in content['takes']):
            blockers.append(f'Prepare the preview and comparison media for {title}.')
    return blockers


def assemble_package(draft, examples, media: ComparisonMedia):
    """Pure package assembly from logical content facts, preserving legacy ordering."""
    examples = {example.ref: example for example in examples}
    groups = []
    for context, brief in draft['brief']['contexts'].items():
        example = examples[brief['destination_ref'] + '-v1']
        content = deepcopy(media.content(example))
        content['instruction'] = draft.get('comparison_instructions', {}).get(example.creative_ref, example.instruction)
        preview_hash = content['preview_sha256']
        groups.append({
            'context': context, 'title': brief['title'], 'creative_version': example.creative_ref,
            'preview_asset': example.preview,
            'preview_path': (f'/viewer/media/{example.creative_ref}/{example.ref}/preview?sha256={preview_hash}'
                             if preview_hash else None),
            'comparison_version': example.ref, 'content': content,
            'placements': [
                {'demo_id': row['id'], 'title': row['title'], 'source': row['source'],
                 'label': ('Catalog candidate · inventory unverified' if row['source'] in {'licensed', 'creator_supplied'}
                           else 'Fictional placement'),
                 **({'catalog_ref': row['catalog_ref']} if 'catalog_ref' in row else {}),
                 **({'source_reference': row['source_reference']} if 'source_reference' in row else {})}
                for row in draft['placements'] if row['creative'] == context],
        })
    references = [(group['comparison_version'], package_fingerprint(group['content'])) for group in groups]
    for group, (_, fingerprint) in zip(groups, references):
        query = [('ad', group['creative_version']), ('content', fingerprint)]
        query.extend(('reviewed', f'{ref}:{digest}') for ref, digest in references)
        group['viewer_path'] = '/viewer?' + urlencode(query)
    return {
        'campaign_id': draft['campaign_id'], 'revision': draft['revision'],
        'data_label': ('Catalog candidates · inventory unverified'
                       if any(row['source'] in {'licensed', 'creator_supplied'} for row in draft['placements'])
                       else 'Fictional placements for an offline sample'),
        'title': draft['brief']['title'],
        'brief': {'id': draft['brief']['id'], 'revision': draft['brief']['revision']},
        'policy': {'id': draft['policy']['id'], 'revision': draft['policy']['revision']},
        'proposed_setup': {'objective': draft['brief']['goal'], 'format': 'YouTube video ad example',
                           'budget': 'Unset for the offline sample', 'schedule': 'Unscheduled'},
        'groups': groups,
        **({'instruction_test': draft['instruction_test']} if 'instruction_test' in draft else {}),
        **({'instruction_reuse': draft['instruction_reuse']} if 'instruction_reuse' in draft else {}),
    }


class PlannerContext:
    def __init__(self, drafts, examples, media: ComparisonMedia):
        self.drafts, self.examples, self.media = drafts, tuple(examples), media
        if (not self.examples or any(example.scope != drafts.scope for example in self.examples)
                or len({example.ref for example in self.examples}) != len(self.examples)
                or len({example.creative_ref for example in self.examples}) != len(self.examples)):
            raise PermissionError("Supply the brand's own comparison catalog.")

    def _scope(self, revision):
        self.drafts.require('youtube:campaign.read')
        if self.drafts.live or type(revision) is not int or not 1 <= revision < 2**63:
            raise ValueError('Choose a valid sample campaign revision.')
        return self.drafts.scope.client_id, self.drafts.scope.brand_id, self.drafts.campaign_id

    def package_review(self, records: PlannerContextRepository, draft_repo: DraftRepository, revision):
        scope = self._scope(revision)
        latest = self.drafts.read_from(draft_repo)
        draft = latest if latest['revision'] == revision else self.drafts.read_from(draft_repo, revision)
        if draft is None:
            raise ValueError('Campaign revision unavailable.')
        draft = {**draft, 'placements': self.drafts._validate_from(draft_repo, draft['placements'], draft['brief']['contexts'])}
        package = assemble_package(draft, self.examples, self.media)
        fingerprint = package_fingerprint(package)
        row = records.approval_row(*scope, revision, fingerprint)
        approval = {'actor_id': row[0], 'approved_at': row[1]} if row else None
        return {'package': package, 'fingerprint': fingerprint, 'approval': approval,
                'current_revision': latest['revision'], 'blockers': package_blockers(package)}

    def saved_review(self, records: PlannerContextRepository, revision, fingerprint, review_id=None):
        scope = self._scope(revision)
        row = records.saved_review_row(*scope, revision, fingerprint, VIEWER_ATTRIBUTION, review_id)
        return {'id': row[0], 'created_at': row[1], **json.loads(row[2])} if row else None

    def started_for_package(self, records: PlannerContextRepository, package):
        self._scope(package['revision'])
        if package['campaign_id'] != self.drafts.campaign_id:
            raise ValueError('Choose a valid sample campaign revision.')
        test_id = package_fingerprint({'scope': vars(self.drafts.scope), 'campaign': package['campaign_id'],
                                       'revision': package['revision'],
                                       'fingerprint': package_fingerprint(package)})[:32]
        return test_id if records.started_test_exists(test_id, self.drafts.scope.client_id,
                                                      self.drafts.scope.brand_id) else None

    def correction_for_comparison(self, records: PlannerContextRepository, package, creative):
        scope = self._scope(package['revision'])
        if package['campaign_id'] != self.drafts.campaign_id:
            raise ValueError('Choose a valid sample campaign revision.')
        group = next(group for group in package['groups'] if group['creative_version'] == creative)
        row = records.correction_row(*scope, creative, group['comparison_version'],
                                     comparison_identity(group, keep_takes=True), comparison_identity(group))
        if row is None:
            return None
        correction_id, kind, note, review_id, actor, created_at = row
        return {'id': correction_id, 'kind': kind, 'label': CORRECTION_CHOICES[kind], 'note': note,
                'review_id': review_id, 'actor_id': actor, 'created_at': created_at}

    def pin(self, records: PlannerContextRepository, draft_repo: DraftRepository, draft):
        review = self.package_review(records, draft_repo, draft['revision'])
        saved = self.saved_review(records, draft['revision'], review['fingerprint'])
        return {'fingerprint': review['fingerprint'],
                'reporting_scenario': saved['sample_delivery']['scenario'] if saved else 'balanced',
                'instruction_test_id': self.started_for_package(records, review['package'])}

    def read_campaign(self, records: PlannerContextRepository, draft_repo: DraftRepository, source):
        draft = self.drafts.read_from(draft_repo)
        package = self.package_review(records, draft_repo, draft['revision'])['package']
        corrections = [self.correction_for_comparison(records, package, group['creative_version'])
                       for group in package['groups']]
        return {'brief': draft['brief'], 'policy': draft['policy'], 'revision': draft['revision'],
                'measurement_capabilities': measurement_capabilities(),
                'draft_permission': source.get('draft_permission', 'none'),
                'package_approved': self.package_review(records, draft_repo, draft['revision'])['approval'] is not None,
                'reporting_scenario': source.get('reporting_scenario', 'balanced'),
                'instruction_test_id': source.get('instruction_test_id'),
                'placements': [{key: row[key] for key in ('id', 'creative', 'source')} for row in draft['placements'][:30]],
                'placement_count': len(draft['placements']),
                'buyer_corrections': [item for item in corrections if item]}
