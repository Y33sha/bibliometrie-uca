"""Sérialisation JSON stable et empreinte de détection de changement.

La sérialisation trie les clés et s'encode en UTF-8 compact : deux valeurs égales ont la même sérialisation. L'empreinte est le XXH3 128 bits de cette sérialisation, sans usage cryptographique.
"""

import orjson
import xxhash

from domain.types import JsonValue


def stable_json_bytes(value: JsonValue) -> bytes:
    """Sérialise une valeur en JSON stable."""
    return orjson.dumps(value, option=orjson.OPT_SORT_KEYS)


def fingerprint(value: JsonValue) -> str:
    """Empreinte de la sérialisation stable d'une valeur. Implémente le port `Fingerprinter`."""
    return xxhash.xxh3_128_hexdigest(stable_json_bytes(value))
