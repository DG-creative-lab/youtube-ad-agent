"""Immutable permitted catalogs and validated placement proposals."""
from contextlib import closing
import json
import sqlite3
from typing import Protocol

from .access import LOCAL_BRAND
from .handoff import package_fingerprint
from .placements import rule_assignment
from scripts.campaign_drafts import PackageConflict, VIDEO_ID


class PlacementClassifier(Protocol):
    def classify(self, rows: list[dict], contexts: dict) -> list[dict]: ...


class SimulatedClassifier:
    route = 'simulated_decision'
    """Authored decision-model stand-in; no live Jev calls or accuracy claims."""
    def classify(self, rows, contexts):
        return [{"id": row["video_id"], "context": rule_assignment(row["description"])} for row in rows]


class PlacementDiscovery:
    def __init__(self, drafts):
        self.drafts = drafts
        with closing(sqlite3.connect(drafts.path)) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS placement_catalogs (
                id TEXT PRIMARY KEY, client_id TEXT NOT NULL, brand_id TEXT NOT NULL,
                campaign_id TEXT NOT NULL, label TEXT NOT NULL, snapshot TEXT NOT NULL)''')

    def register(self, label, rows):
        self.drafts.operator.require_brand(LOCAL_BRAND)
        if not isinstance(label, str) or not label.strip() or len(label) > 100:
            raise ValueError('Name the catalog in up to 100 characters.')
        if not isinstance(rows, list) or not 1 <= len(rows) <= 200:
            raise ValueError('Supply 1 to 200 independently supplied catalog rows.')
        seen = set()
        clean = []
        for row in rows:
            if not isinstance(row, dict) or set(row) - {'video_id', 'description', 'source', 'source_reference'}:
                raise ValueError('Use video_id, description, source and source_reference.')
            video, text, source = row.get('video_id'), row.get('description'), row.get('source')
            reference = row.get('source_reference', 'Authored offline fixture' if source == 'synthetic' else '')
            if (not isinstance(video, str) or not VIDEO_ID.fullmatch(video) or video in seen
                    or not isinstance(text, str) or not text.strip() or len(text) > 3000
                    or not isinstance(source, str) or source not in {'synthetic', 'creator_supplied', 'licensed'}
                    or not isinstance(reference, str) or not reference.strip() or len(reference) > 500):
                raise ValueError('Use unique video IDs, permitted descriptions and an independent source reference.')
            seen.add(video)
            clean.append(dict(video_id=video, description=text, source=source, source_reference=reference))
        identity = {'scope': vars(LOCAL_BRAND), 'campaign': self.drafts.campaign_id, 'rows': clean}
        catalog_id = package_fingerprint(identity)[:32]
        with closing(sqlite3.connect(self.drafts.path)) as db, db:
            db.execute('INSERT INTO placement_catalogs VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING',
                       (catalog_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.drafts.campaign_id,
                        label.strip(), json.dumps(clean)))
            for row in clean:
                ref = package_fingerprint({**identity, 'video': row['video_id']})[:32]
                db.execute('''INSERT INTO placement_catalog_entries
                           (ref,client_id,brand_id,campaign_id,video_id,title,source,source_reference)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING''',
                           (ref, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.drafts.campaign_id,
                            row['video_id'], row['description'], row['source'], row['source_reference']))
        return catalog_id

    def read(self, db, catalog_id):
        self.drafts.operator.require_brand(LOCAL_BRAND)
        row = db.execute('SELECT snapshot FROM placement_catalogs WHERE id=? AND client_id=? AND brand_id=? AND campaign_id=?',
                         (catalog_id, LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.drafts.campaign_id)).fetchone()
        if row is None:
            raise ValueError('Choose an available catalog for this campaign.')
        return json.loads(row[0])

    def list(self):
        self.drafts.operator.require_brand(LOCAL_BRAND)
        with closing(sqlite3.connect(self.drafts.path)) as db:
            return [{'id': key, 'label': label, 'count': len(json.loads(snapshot))}
                    for key, label, snapshot in db.execute(
                        'SELECT id,label,snapshot FROM placement_catalogs WHERE client_id=? AND brand_id=? AND campaign_id=?',
                        (LOCAL_BRAND.client_id, LOCAL_BRAND.brand_id, self.drafts.campaign_id))]

    def save(self, db, catalog_id, expected_revision, assignments, selected_ids):
        rows = self.read(db, catalog_id)
        if (not isinstance(selected_ids, list) or not selected_ids or any(not isinstance(item, str) for item in selected_ids)
                or len(selected_ids) != len(set(selected_ids))):
            raise ValueError('Choose distinct classified video IDs.')
        allowed = {row['id']: row['context'] for row in assignments if row['context'] != 'review'}
        if any(item not in allowed for item in selected_ids):
            raise ValueError('Only classified, unambiguous catalog videos can be saved.')
        current = self.drafts._read(db)
        if current['revision'] != expected_revision:
            raise PackageConflict('The campaign changed. Start a new placement run from the latest revision.')
        identity = {'scope': vars(LOCAL_BRAND), 'campaign': self.drafts.campaign_id, 'rows': rows}
        chosen = {row['id']: row for row in current['placements']}
        for row in rows:
            if row['video_id'] in selected_ids and row['video_id'] not in chosen:
                chosen[row['video_id']] = {'id': row['video_id'], 'title': row['description'],
                    'creative': allowed[row['video_id']], 'source': row['source'],
                    'source_reference': row['source_reference'],
                    'catalog_ref': package_fingerprint({**identity, 'video': row['video_id']})[:32]}
        return self.drafts.save({'campaign_id': self.drafts.campaign_id, 'revision': expected_revision,
                                 'placements': list(chosen.values())}, connection=db)
