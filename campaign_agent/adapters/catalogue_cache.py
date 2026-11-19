"""Bounded process-local catalogue entries and cursors."""
from collections import OrderedDict
import secrets
from threading import Lock

from campaign_agent.ports.inference import ProviderError


class CatalogueCache:
    """Bounded noncredential cache. Callers prove current scope/key before every access."""
    def __init__(self):
        self.lock=Lock();self.entries=OrderedDict();self.busy=set()

    def invalidate(self, connection):
        with self.lock:
            self.entries.pop(connection,None)

    def get(self, connection, now):
        with self.lock:
            entry=self.entries.get(connection)
            if entry and entry['expires_at']>now:
                return entry
            self.entries.pop(connection,None)

    def begin(self, connection):
        with self.lock:
            if connection in self.busy:
                raise ProviderError('admission_busy')
            self.busy.add(connection)

    def finish(self, connection, entry=None):
        with self.lock:
            self.busy.discard(connection)
            if entry is not None:
                self.entries[connection]=entry
                while len(self.entries)>16:
                    self.entries.popitem(last=False)

    def page(self, entry, search, cursor):
        with self.lock:
            offset=0
            if cursor is not None:
                if cursor not in entry['cursors'] or entry['cursors'][cursor][0]!=search:
                    raise ProviderError('selection_stale')
                offset=entry['cursors'][cursor][1]
            query = search.casefold()
            compact_query = "".join(character for character in query if character.isalnum())
            rows = []
            for row in entry["models"]:
                name = (row["id"] + " " + row["name"]).casefold()
                compact_name = "".join(character for character in name if character.isalnum())
                if query in name or compact_query and compact_query in compact_name:
                    rows.append(row)
            rows.sort(key=lambda row: (row["state"] != "eligible", row["id"]))
            next_cursor=None
            if offset+20<len(rows):
                next_cursor=secrets.token_hex(32)
                entry['cursors'][next_cursor]=(search,offset+20)
                while len(entry['cursors'])>128:
                    entry['cursors'].pop(next(iter(entry['cursors'])))
            return rows[offset:offset+20],next_cursor
