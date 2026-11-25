"""Explicit publication grants for exact approved comparison content."""
import json

from .handoff import caption_bytes, example_content, media_sha256, package_fingerprint, read_media
from .measurement import ViewerNotFound
from .ports.viewer_storage import PublishedGrant, ViewerReader, ViewerStorage
from campaign_agent.domain.errors import PackageConflict


_REPUBLICATION_REQUIRED = (
    'Public comparison links for this package have expired or been revoked. '
    'Link renewal is not supported in this offline slice. '
    'Prepare and approve a new package revision before exporting. '
    'Existing setup destinations will not be changed.'
)


class Publications:
    def __init__(self, storage: ViewerStorage, assets, viewer_for, *, clock, new_token):
        self.storage, self.assets, self.viewer_for = storage, assets, viewer_for
        self.clock, self._new_token = clock, new_token

    def publish(self, runtime, campaign_id, revision, fingerprint):
        # Publication is an export effect. A read or a model tool cannot publish content.
        drafts = runtime.drafts
        drafts.require('youtube:campaign.export')
        key = (drafts.scope.client_id, drafts.scope.brand_id, campaign_id, revision, fingerprint)
        with self.storage.write() as unit:
            package = drafts.require_approved_from(unit.drafts, campaign_id, revision, fingerprint)['package']
            drafts.require('youtube:campaign.export')
            for group in package['groups']:
                grant = PublishedGrant(*key, group['creative_version'], json.dumps(group))
                unit.add_publication(self._new_token(), grant, self.clock() + 3600)
            links = self._active_links(unit, key)
            if {link['creative_ref'] for link in links} != {group['creative_version'] for group in package['groups']}:
                # Retrying cannot revive old grants. Roll back any sibling inserts.
                raise PackageConflict(_REPUBLICATION_REQUIRED)
            unit.commit()
            return links

    def _active_links(self, records: ViewerReader, key):
        return [{'creative_ref': creative, 'path': '/viewer?attribution=' + token}
                for token, creative in records.active_links(key, self.clock())]

    def active_links(self, drafts, revision, fingerprint):
        key = (drafts.scope.client_id, drafts.scope.brand_id, drafts.campaign_id, revision, fingerprint)
        with self.storage.read() as records:
            drafts._require_owner(records.drafts)
            return self._active_links(records, key)

    def _active_grant(self, records: ViewerReader, token):
        if not isinstance(token, str) or len(token) != 43:
            raise ViewerNotFound('This published comparison is unavailable.')
        grant = records.active_grant(token, self.clock())
        if grant is None:
            raise ViewerNotFound('This published comparison is unavailable.')
        return grant

    def _grant(self, token):
        with self.storage.read() as records:
            return self._active_grant(records, token)

    def _comparison(self, grant):
        examples, media_dir = self.assets(grant.client_id, grant.brand_id)
        group = json.loads(grant.snapshot)
        example = next((e for e in examples if e.ref == group['comparison_version']
                        and e.creative_ref == group['creative_version'] == grant.creative_ref
                        and (e.scope.client_id, e.scope.brand_id) == (grant.client_id, grant.brand_id)), None)
        if example is None:
            raise ViewerNotFound('This published comparison is unavailable.')
        actual = example_content(example, media_dir)
        actual['instruction'] = group['content']['instruction']
        if actual != group['content'] or any(not take['sha256'] for take in actual['takes']):
            raise PackageConflict('The published comparison media changed.')
        return group, example, media_dir

    def _require_current(self, records: ViewerReader, token, grant):
        if self._active_grant(records, token) != grant:
            raise ViewerNotFound('This published comparison is unavailable.')

    def resolve(self, token):
        grant = self._grant(token)
        return self._comparison(grant)

    def open(self, token, visit_id, rehearsal=False):
        grant = self._grant(token)
        group, example, _ = self._comparison(grant)
        viewer = self.viewer_for([example], grant.campaign_id)
        with self.storage.write() as unit:
            self._require_current(unit, token, grant)
            result = viewer.open_from(unit, group['creative_version'], group['comparison_version'], visit_id,
                                      content_fingerprint=package_fingerprint(group['content']), ad_link_id=token,
                                      rehearsal=rehearsal)
            unit.commit()
        result['creative_ref'] = group['creative_version']
        result['example']['instruction'] = group['content']['instruction']
        for take in result['example']['takes']:
            take['url'] = f"/published/{token}/{take['id']}"
        result['example']['captions'] = f'/published/{token}/captions'
        return result

    def approved_links(self, package, rows):
        if any(not active or expires_at <= self.clock() for _, _, _, active, expires_at in rows):
            raise PackageConflict(_REPUBLICATION_REQUIRED)
        published = {creative: (token, json.loads(snapshot)) for token, creative, snapshot, _, _ in rows}
        links = []
        for group in package['groups']:
            value = published.get(group['creative_version'])
            if value is None or value[1]['content'] != group['content']:
                raise PackageConflict('Export this approved setup to publish its comparisons before validating.')
            token, _ = value
            links.append({'context': group['context'], 'creative_ref': group['creative_version'],
                'comparison_ref': group['comparison_version'], 'content_fingerprint': package_fingerprint(group['content']),
                'id': token, 'path': '/viewer?attribution=' + token})
        return links

    def event(self, payload):
        if set(payload) != {'creative_ref', 'visit_id', 'example_ref', 'event_id', 'kind', 'take'}:
            raise ValueError('Send an allowed viewer event.')
        with self.storage.read() as records:
            link = records.visit_link_row(payload['visit_id'])
            if link is None:
                raise ViewerNotFound('This visit is unavailable.')
            token = link[0]
            grant = self._active_grant(records, token)
        group, example, _ = self._comparison(grant)
        if (payload['creative_ref'], payload['example_ref']) != (group['creative_version'], group['comparison_version']):
            raise ViewerNotFound('This visit is unavailable.')
        viewer = self.viewer_for([example], grant.campaign_id)
        with self.storage.write() as unit:
            self._require_current(unit, token, grant)
            result = viewer.record_from(unit, **payload,
                                        expected_attribution=(package_fingerprint(group['content']), token))
            unit.commit()
            return result

    def media(self, token, take):
        grant = self._grant(token)
        group, example, media_dir = self._comparison(grant)
        if take == 'captions':
            data, content_type = caption_bytes(example), 'text/vtt; charset=utf-8'
        else:
            source = next((item for item in group['content']['takes'] if item['id'] == take), None)
            if source is None:
                raise ViewerNotFound('This sample is unavailable.')
            data = read_media(media_dir, source['asset'])
            if media_sha256(data) != source['sha256']:
                raise PackageConflict('The published comparison media changed.')
            content_type = 'video/mp4' if source['asset'].endswith('.mp4') else 'audio/mpeg'
        with self.storage.read() as records:
            self._require_current(records, token, grant)
        return data, content_type
