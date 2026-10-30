"""Empreinte de détection des changements des payloads sources.

Un payload réémis à l'identique, au bruit volatil près, garde son empreinte : sa ligne de `staging` reste en l'état, et la phase `normalize` la saute. La sérialisation stable (`stable_json_bytes`) est aussi le contenu écrit dans le raw store.
"""

from collections.abc import Mapping

from domain.sources.registry import Source
from domain.types import JsonValue
from pipeline.ingestion.adapters import ADAPTERS
from pipeline.ingestion.common.fingerprint import fingerprint


def change_detection_hash(source: str, raw_data: Mapping[str, JsonValue]) -> str:
    """Renvoie l'empreinte d'un payload, calculée sur une copie sans le bruit volatil propre à la source (`SourceAdapter.strip_volatile`).

    Le payload stocké reste fidèle à la source.

    Le moissonnage et la réhydratation depuis le raw store partagent ce calcul : une ligne réhydratée garde son empreinte au moissonnage suivant. Pour une source sans bruit volatil, l'empreinte égale `fingerprint(raw_data)`.
    """
    strip_volatile = ADAPTERS[Source(source)].strip_volatile
    return fingerprint(dict(strip_volatile(raw_data) if strip_volatile else raw_data))
