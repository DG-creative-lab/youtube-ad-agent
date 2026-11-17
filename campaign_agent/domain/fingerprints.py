"""Stable fingerprints shared by campaign commands and effect adapters."""
import hashlib
import json


def package_fingerprint(package):
    encoded = json.dumps(package, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
