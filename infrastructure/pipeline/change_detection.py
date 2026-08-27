"""Hash de détection de changement des payloads sources.

Pilote l'UPSERT `staging` (réécriture de `raw_data` + repassage `processed`) : un payload réémis à l'identique au sens métier ne déclenche ni réécriture ni re-normalisation. La forme canonique sérialisée sert aussi de contenu écrit au raw store, d'où `md5(canonical_json_bytes(d)) == compute_hash(d)`.
"""

import hashlib
import json
from collections.abc import Callable

from infrastructure.sources.hal.hash_normalize import strip_volatile_for_hash


def canonical_json_bytes(raw_data: dict) -> bytes:
    """Sérialise un payload en JSON canonique (clés triées, compact, UTF-8).

    Forme unique partagée par `compute_hash` (empreinte du payload) et le raw store (contenu écrit) : garantit `md5(canonical_json_bytes(d)) == compute_hash(d)`.
    """
    return json.dumps(raw_data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def compute_hash(raw_data: dict) -> str:
    """Calcule le hash MD5 du JSON canonique (clés triées, compact)."""
    return hashlib.md5(canonical_json_bytes(raw_data), usedforsecurity=False).hexdigest()


# Neutralisation, par source, du bruit volatil avant calcul du hash de détection de changement. Une source absente n'est pas normalisée (hash sur le payload fidèle).
# HAL : horodatage de génération enfoui dans le TEI `label_xml`.
_HASH_NORMALIZERS: dict[str, Callable[[dict], dict]] = {
    "hal": strip_volatile_for_hash,
}


def change_detection_hash(source: str, raw_data: dict) -> str:
    """Hash pilotant l'UPSERT `staging` (réécriture `raw_data` + `processed`).

    Calculé sur une copie du payload dont le bruit volatil propre à la source est neutralisé (cf. `_HASH_NORMALIZERS`), pour qu'un champ réémis à l'identique métier ne déclenche ni réécriture ni re-normalisation. Le payload stocké (`staging.raw_data`, raw store) reste, lui, fidèle à la source.

    Point d'entrée unique du hash de détection : partagé par l'UPSERT d'extraction et la réhydratation depuis le raw store, pour qu'ils s'accordent (une ligne réhydratée ne re-diverge pas au moissonnage suivant). Pour les sources sans normaliseur, égale `compute_hash(raw_data)`.
    """
    normalize = _HASH_NORMALIZERS.get(source)
    return compute_hash(normalize(raw_data) if normalize else raw_data)
