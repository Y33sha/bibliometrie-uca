"""Hash de détection de changement des payloads sources.

Pilote l'UPSERT `staging` (réécriture de `raw_data` + repassage `processed`) : un payload réémis à l'identique au sens métier ne déclenche ni réécriture ni re-normalisation. La sérialisation stable (`stable_json_bytes`) sert aussi de contenu écrit au raw store.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.fingerprint import fingerprint


def change_detection_hash(source: str, raw_data: Mapping[str, JsonValue]) -> str:
    """Hash pilotant l'UPSERT `staging` (réécriture `raw_data` + `processed`).

    Calculé sur une copie du payload dont le bruit volatil propre à la source est neutralisé (`SourceAdapter.strip_volatile`), pour qu'un champ réémis à l'identique métier ne déclenche ni réécriture ni re-normalisation. Le payload stocké (`staging.raw_data`, raw store) reste, lui, fidèle à la source.

    Point d'entrée unique du hash de détection : partagé par l'UPSERT d'extraction et la réhydratation depuis le raw store, pour qu'ils s'accordent (une ligne réhydratée ne re-diverge pas au moissonnage suivant). Pour les sources sans normaliseur, égale `fingerprint(raw_data)`.
    """
    strip_volatile = ADAPTERS[Source(source)].strip_volatile
    return fingerprint(dict(strip_volatile(raw_data) if strip_volatile else raw_data))
