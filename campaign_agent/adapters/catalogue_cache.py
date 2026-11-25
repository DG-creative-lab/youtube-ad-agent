"""Bounded process-local catalogue entries and cursors."""
from collections import OrderedDict
from decimal import Decimal
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

    def page(self, entry, search, cursor, *, tools_only=False, max_input_price=None, max_output_price=None, sort="available"):
        with self.lock:
            signature = [search, tools_only, max_input_price, max_output_price, sort]
            offset=0
            if cursor is not None:
                if cursor not in entry['cursors'] or entry['cursors'][cursor][0]!=signature:
                    raise ProviderError('selection_stale')
                offset=entry['cursors'][cursor][1]
            query = search.casefold()
            compact_query = "".join(character for character in query if character.isalnum())
            rows = []
            for row in entry["models"]:
                name = (row["id"] + " " + row["name"]).casefold()
                compact_name = "".join(character for character in name if character.isalnum())
                matches = query in name or compact_query and compact_query in compact_name
                if not matches or tools_only and not row.get("supports_tools"):
                    continue
                if any(limit is not None and (row[field] is None or Decimal(row[field]) > Decimal(limit))
                       for field, limit in (("input_usd_per_million", max_input_price),
                                            ("output_usd_per_million", max_output_price))):
                    continue
                rows.append(row)
            if sort in {"pricing-low-to-high", "pricing-high-to-low"}:
                descending = sort == "pricing-high-to-low"
                def price_order(row):
                    values = (row["input_usd_per_million"], row["output_usd_per_million"])
                    unknown = any(value is None for value in values)
                    amount = sum(Decimal(value) for value in values) if not unknown else Decimal(0)
                    return (unknown, -amount if descending else amount, row["id"])
                rows.sort(key=price_order)
            elif sort in {"most-popular", "intelligence-high-to-low"}:
                ranks = {model: index for index, model in enumerate(entry.get("provider_order", []))}
                rows.sort(key=lambda row: (ranks.get(row["id"], len(ranks)), row["id"]))
            else:
                rows.sort(key=lambda row: (row["state"] != "eligible", row["id"]))
            next_cursor=None
            if offset+20<len(rows):
                next_cursor=secrets.token_hex(32)
                entry['cursors'][next_cursor]=(signature,offset+20)
                while len(entry['cursors'])>128:
                    entry['cursors'].pop(next(iter(entry['cursors'])))
            return rows[offset:offset+20],next_cursor
