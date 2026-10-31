"""Hash do estado de uma entidade (plano, seção 7.3).

Cópia idêntica de client/sync_client/state_hash.py. O teste
tests/test_hash_equality.py garante que as duas implementações coincidem.
"""
import hashlib
import json


def entity_hash(entity_id, data, deleted):
    doc = {"entity_id": entity_id, "data": data, "deleted": int(deleted)}
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
