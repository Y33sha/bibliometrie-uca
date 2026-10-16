"""Détection du pays d'une adresse par **nom de lieu** : candidats `institution` et `city`.

Cherche dans tout le texte normalisé des adresses à traiter (`candidates_dirty`) les noms d'institutions et de villes connus (`place_name_forms`), chacun rattaché à un pays, via un automate Aho-Corasick (`PlaceNameDetector`) par nature de lieu. Chaque pays trouvé devient un candidat du moyen de même nature : des lieux de pays différents donnent plusieurs candidats. Les candidats de ces deux moyens sont recalculés en entier pour chaque adresse traitée.

Ne dépend que du port `CountryQueries` et du domaine ; le commit est laissé au caller.
"""

import logging

from sqlalchemy import Connection

from domain.countries import PlaceNameKind
from domain.country_detection import CountryDetectionMethod
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.structures.countries.countries_queries import CountryQueries
from pipeline.transformation.structures.countries.place_name_detector import PlaceNameDetector

_METHODS = {
    PlaceNameKind.INSTITUTION: CountryDetectionMethod.INSTITUTION,
    PlaceNameKind.CITY: CountryDetectionMethod.CITY,
}
_LABELS = {PlaceNameKind.INSTITUTION: "institutions", PlaceNameKind.CITY: "villes"}


def run(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> PhaseMetrics:
    """Ajoute les candidats `institution` et `city` des adresses à traiter.

    `seen` = adresses examinées, `new` = adresses qui reçoivent un candidat.
    """
    etape(logger, "Pays des adresses d'après les noms de villes et d'institutions")
    rows = queries.fetch_dirty_addresses_normalized(conn)
    added = 0
    for kind, method in _METHODS.items():
        detector = PlaceNameDetector(queries.load_place_forms(conn, kind))
        proposals = [
            (addr_id, sorted(isos))
            for addr_id, normalized_text in rows
            if (isos := detector.detect(normalized_text))
        ]
        n = queries.replace_candidates_of_dirty_addresses(conn, method, proposals)
        logger.info(
            "%s%s : pays trouvé pour %s",
            BRANCHE if method is CountryDetectionMethod.INSTITUTION else DERNIERE_BRANCHE,
            _LABELS[kind],
            accord(n, "adresse"),
        )
        added += n
    return PhaseMetrics(seen=len(rows), new=added)
