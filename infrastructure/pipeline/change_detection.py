"""Hash de détection de changement des payloads sources.

Pilote l'UPSERT `staging` (réécriture de `raw_data` + repassage `processed`) : un payload réémis à l'identique au sens métier ne déclenche ni réécriture ni re-normalisation. La sérialisation stable (`stable_json_bytes`) sert aussi de contenu écrit au raw store.
"""

from collections.abc import Callable, Mapping

from domain.types import JsonValue
from infrastructure.fingerprint import fingerprint
from infrastructure.sources.datacite import hash_normalize as datacite_hash
from infrastructure.sources.hal import hash_normalize as hal_hash

# Neutralisation, par source, du bruit volatil avant calcul du hash de détection de changement. Une source absente n'est pas normalisée (hash sur le payload fidèle).
# HAL : horodatage de génération enfoui dans le TEI `label_xml`.
# DataCite : champs propres à la route de lecture, dates d'enregistrement et compteurs.
_HASH_NORMALIZERS: dict[str, Callable[[Mapping[str, JsonValue]], Mapping[str, JsonValue]]] = {
    "hal": hal_hash.strip_volatile_for_hash,
    "datacite": datacite_hash.strip_volatile_for_hash,
}


def change_detection_hash(source: str, raw_data: Mapping[str, JsonValue]) -> str:
    """Hash pilotant l'UPSERT `staging` (réécriture `raw_data` + `processed`).

    Calculé sur une copie du payload dont le bruit volatil propre à la source est neutralisé (cf. `_HASH_NORMALIZERS`), pour qu'un champ réémis à l'identique métier ne déclenche ni réécriture ni re-normalisation. Le payload stocké (`staging.raw_data`, raw store) reste, lui, fidèle à la source.

    Point d'entrée unique du hash de détection : partagé par l'UPSERT d'extraction et la réhydratation depuis le raw store, pour qu'ils s'accordent (une ligne réhydratée ne re-diverge pas au moissonnage suivant). Pour les sources sans normaliseur, égale `fingerprint(raw_data)`.
    """
    normalize = _HASH_NORMALIZERS.get(source)
    return fingerprint(dict(normalize(raw_data) if normalize else raw_data))
