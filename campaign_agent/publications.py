"""Explicit publication grants for exact approved comparison content."""
from contextlib import closing
import json
import secrets
import sqlite3
from time import time

from .handoff import caption_bytes, example_content, media_sha256, package_fingerprint, read_media
from .measurement import ViewerMeasurement, ViewerNotFound
from scripts.campaign_drafts import PackageConflict


_REPUBLICATION_REQUIRED = (
    'Public comparison links for this package have expired or been revoked. '
    'Link renewal is not supported in this offline slice. '
    'Prepare and approve a new package revision before exporting. '
    'Existing setup destinations will not be changed.'
)


class Publications:
    def __init__(self, path, assets, *, clock=time):
        self.path, self.assets, self.clock = path, assets, clock
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS public_comparisons (
                id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL, revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                creative_ref TEXT NOT NULL, snapshot TEXT NOT NULL, expires_at REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                UNIQUE(campaign_id,revision,fingerprint,creative_ref))''')

    def publish(self, runtime, campaign_id, revision, fingerprint):
        # Publication is an export effect. A read or a model tool cannot publish content.
        runtime.drafts.require('youtube:campaign.export')
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            package = runtime.drafts.require_approved_package(db, campaign_id, revision, fingerprint)['package']
            scope = runtime.drafts.scope
            runtime.drafts.require('youtube:campaign.export')
            for group in package['groups']:
                db.execute('''INSERT INTO public_comparisons
                    (id,client_id,brand_id,campaign_id,revision,fingerprint,creative_ref,snapshot,expires_at)
                    VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING''',
                    (secrets.token_urlsafe(32), scope.client_id, scope.brand_id, campaign_id, revision, fingerprint,
                     group['creative_version'], json.dumps(group), self.clock() + 3600))
            links = [{'creative_ref': creative, 'path': '/viewer?attribution=' + key}
                    for key, creative in db.execute('SELECT id,creative_ref FROM public_comparisons '
                        'WHERE campaign_id=? AND revision=? AND fingerprint=? AND active=1 AND expires_at>?',
                        (campaign_id, revision, fingerprint, self.clock()))]
            if {link['creative_ref'] for link in links} != {group['creative_version'] for group in package['groups']}:
                # Fail the whole export and roll back any sibling inserts. In particular,
                # retrying export cannot revive a revoked grant or replace setup destinations.
                raise PackageConflict(_REPUBLICATION_REQUIRED)
            return links

    def resolve(self, token):
        if not isinstance(token, str) or len(token) != 43:
            raise ViewerNotFound('This published comparison is unavailable.')
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT client_id,brand_id,campaign_id,snapshot FROM public_comparisons '
                             'WHERE id=? AND active=1 AND expires_at>?', (token, self.clock())).fetchone()
        if row is None:
            raise ViewerNotFound('This published comparison is unavailable.')
        examples, media_dir = self.assets(row[0], row[1])
        group = json.loads(row[3])
        example = next((e for e in examples if e.ref == group['comparison_version']
                        and e.creative_ref == group['creative_version']), None)
        if example is None:
            raise ViewerNotFound('This published comparison is unavailable.')
        actual = example_content(example, media_dir)
        actual['instruction'] = group['content']['instruction']
        if actual != group['content'] or any(not take['sha256'] for take in actual['takes']):
            raise PackageConflict('The published comparison media changed.')
        viewer = ViewerMeasurement(self.path, [example], campaign_id=row[2])
        return row[2], group, example, media_dir, viewer

    def open(self, token, visit_id, rehearsal=False):
        _, group, _, _, viewer = self.resolve(token)
        with closing(viewer.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require_active(db, token)
            result = viewer.open_example(group['creative_version'], group['comparison_version'], visit_id,
                        content_fingerprint=package_fingerprint(group['content']), ad_link_id=token,
                        rehearsal=rehearsal, connection=db)
        result['creative_ref'] = group['creative_version']
        result['example']['instruction'] = group['content']['instruction']
        for take in result['example']['takes']:
            take['url'] = f"/published/{token}/{take['id']}"
        result['example']['captions'] = f'/published/{token}/captions'
        return result

    def approved_links(self, package, fingerprint):
        with closing(sqlite3.connect(self.path)) as db:
            rows = db.execute('SELECT id,creative_ref,snapshot,active,expires_at FROM public_comparisons WHERE campaign_id=? '
                              'AND revision=? AND fingerprint=?',
                              (package['campaign_id'], package['revision'], fingerprint)).fetchall()
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
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute('SELECT ad_link_id FROM viewer_visits WHERE id=?', (payload['visit_id'],)).fetchone()
        if row is None:
            raise ViewerNotFound('This visit is unavailable.')
        _, group, _, _, viewer = self.resolve(row[0])
        if (payload['creative_ref'], payload['example_ref']) != (group['creative_version'], group['comparison_version']):
            raise ViewerNotFound('This visit is unavailable.')
        with closing(viewer.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            self._require_active(db, row[0])
            return viewer.record(**payload, connection=db)

    def _require_active(self, db, token):
        if not db.execute('SELECT 1 FROM public_comparisons WHERE id=? AND active=1 AND expires_at>?',
                          (token, self.clock())).fetchone():
            raise ViewerNotFound('This published comparison is unavailable.')

    def media(self, token, take):
        _, group, example, media_dir, _ = self.resolve(token)
        if take == 'captions':
            return caption_bytes(example), 'text/vtt; charset=utf-8'
        source = next((item for item in group['content']['takes'] if item['id'] == take), None)
        if source is None:
            raise ViewerNotFound('This sample is unavailable.')
        data = read_media(media_dir, source['asset'])
        if media_sha256(data) != source['sha256']:
            raise PackageConflict('The published comparison media changed.')
        return data, 'video/mp4' if source['asset'].endswith('.mp4') else 'audio/mpeg'
