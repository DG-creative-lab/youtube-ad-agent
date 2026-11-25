"""Immutable permitted catalogs and validated placement proposals."""
import json
from campaign_agent.ports.placement_commit import PlacementRepositories
from campaign_agent.ports.planning import PlacementClassifier
from campaign_agent.ports.catalogs import CatalogStorage, CatalogReader, CatalogScope, CatalogRecord, CatalogEntry

from .handoff import package_fingerprint
from .placements import rule_assignment
from campaign_agent.domain.errors import PackageConflict
from campaign_agent.domain.placements import VIDEO_ID


class SimulatedClassifier:
    route = 'simulated_decision'
    """Authored decision-model stand-in; no live Jev calls or accuracy claims."""
    def classify(self, rows, contexts):
        return [{"id": row["video_id"], "context": rule_assignment(row["description"])} for row in rows]


class PlacementDiscovery:
    def __init__(self, drafts, catalog_storage: CatalogStorage):
        self.drafts = drafts
        self.catalog_storage = catalog_storage

    @property
    def _catalog_scope(self):
        return CatalogScope(self.drafts.scope.client_id, self.drafts.scope.brand_id, self.drafts.campaign_id)

    def register(self, label, rows):
        self.drafts.require("youtube:catalog.write")
        self.drafts.require("youtube:campaign.read")
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
        identity = {'scope': vars(self.drafts.scope), 'campaign': self.drafts.campaign_id, 'rows': clean}
        catalog_id = package_fingerprint(identity)[:32]
        # As before, refresh permission before the first SQL/write transaction.
        self.drafts.require("youtube:catalog.write")
        with self.catalog_storage.write() as unit:
            unit.catalogs.add_catalog(CatalogRecord(catalog_id, self._catalog_scope, label.strip(), json.dumps(clean)))
            for row in clean:
                ref = package_fingerprint({**identity, "video": row["video_id"]})[:32]
                unit.catalogs.add_entry(CatalogEntry(ref, self._catalog_scope, row['video_id'],
                                                   row['description'], row['source'], row['source_reference']))
            unit.commit()
        return catalog_id

    def read(self, catalogs: CatalogReader, catalog_id):
        self.drafts.require("youtube:campaign.read")
        row = catalogs.read_snapshot(self._catalog_scope, catalog_id)
        if row is None:
            raise ValueError('Choose an available catalog for this campaign.')
        return json.loads(row[0])

    def read_from(self, catalogs: CatalogReader, catalog_id):
        return self.read(catalogs, catalog_id)

    def list(self):
        self.drafts.require("youtube:campaign.read")
        with self.catalog_storage.read() as catalogs:
            return [{'id': row.id, 'label': row.label, 'count': len(json.loads(row.snapshot))}
                    for row in catalogs.list_catalogs(self._catalog_scope)]

    def save(self, catalog_id, expected_revision, assignments, selected_ids,
             *, repositories: PlacementRepositories):
        rows = self.read(repositories.catalogs, catalog_id)
        if (not isinstance(selected_ids, list) or not selected_ids or any(not isinstance(item, str) for item in selected_ids)
                or len(selected_ids) != len(set(selected_ids))):
            raise ValueError('Choose distinct classified video IDs.')
        allowed = {row['id']: row['context'] for row in assignments if row['context'] != 'review'}
        if any(item not in allowed for item in selected_ids):
            raise ValueError('Only classified, unambiguous catalog videos can be saved.')
        current = self.drafts.read_from(repositories.drafts)
        if current['revision'] != expected_revision:
            raise PackageConflict('The campaign changed. Start a new placement run from the latest revision.')
        identity = {'scope': vars(self.drafts.scope), 'campaign': self.drafts.campaign_id, 'rows': rows}
        chosen = {row['id']: row for row in current['placements']}
        for row in rows:
            if row['video_id'] in selected_ids and row['video_id'] not in chosen:
                chosen[row['video_id']] = {'id': row['video_id'], 'title': row['description'],
                    'creative': allowed[row['video_id']], 'source': row['source'],
                    'source_reference': row['source_reference'],
                    'catalog_ref': package_fingerprint({**identity, 'video': row['video_id']})[:32]}
        return self.drafts.save({'campaign_id': self.drafts.campaign_id, 'revision': expected_revision,
                                 'placements': list(chosen.values())},
                                repository=repositories.drafts)


def model_assignments(arguments, history, contexts):
    assignments = arguments.get("assignments")
    inspected = next((step["result"] for step in reversed(history)
                      if step["tool"] == "inspect_catalog" and "error" not in step["result"]), None)
    known = {row["video_id"] for row in inspected["entries"]} if inspected else set()
    if (set(arguments) != {"assignments"} or not isinstance(assignments, list)
            or not assignments or len(assignments) > len(known)
            or any(not isinstance(row, dict) or set(row) != {"id", "context"}
                   or not isinstance(row["id"], str) or row["id"] not in known
                   or not isinstance(row["context"], str)
                   or row["context"] not in {*contexts, "review"} for row in assignments)
            or len({row["id"] for row in assignments}) != len(assignments)):
        # No model arguments or exception strings are reflected back. Returning an
        # error observation preserves the existing transaction and recovery path.
        return {"error": "Classify only inspected video IDs, once each, using an allowed context ID or review. Inspect the catalog first if no IDs are listed.",
                "code": "invalid_classification", "allowed_contexts": [*contexts, "review"],
                "inspected_video_ids": sorted(known)}
    return {"assignments": assignments, "route": "main_model",
            "label": "Main-model classification of inspected catalog entries"}
