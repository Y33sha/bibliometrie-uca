"""Détection du pays d'une adresse par **nom de lieu** (institution, ville).

Pour les adresses restées sans pays après la détection par nom de pays, cherche dans tout le
texte normalisé — pas seulement le dernier segment — les noms d'institutions et de villes connus
(`place_name_forms`, `kind IN ('institution', 'city')`), chacun rattaché à un pays, via un automate
Aho-Corasick (`PlaceNameDetector`). Le pays n'est écrit (`addresses.countries`, autoritaire) que si
les lieux trouvés désignent un pays unique ; un conflit (pays multiples) est laissé à la suggestion.

Ne dépend que du port `CountryQueries` et du domaine ; le commit est laissé au caller.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.countries.place_name_detector import PlaceNameDetector
from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.countries import CountryQueries


def run(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> PhaseMetrics:
    """Détecte le pays des adresses sans pays via les noms de lieux.

    `seen` = adresses examinées, `new` = adresses résolues (pays unique),
    `extras["conflicts"]` = adresses à pays multiples ignorées.
    """
    forms = queries.load_place_forms(conn)
    logger.info("%d noms de lieux chargés", len(forms))
    if not forms:
        return PhaseMetrics()
    detector = PlaceNameDetector(forms)

    rows = queries.fetch_addresses_missing_country_normalized(conn)
    logger.info("%d adresses sans pays à examiner", len(rows))

    matched: list[tuple[int, list[str]]] = []
    conflicts = 0
    for addr_id, normalized_text in rows:
        isos = detector.detect(normalized_text)
        if len(isos) == 1:
            matched.append((addr_id, [next(iter(isos))]))
        elif len(isos) > 1:
            conflicts += 1

    logger.info("Résolues : %d, conflits (pays multiples, ignorés) : %d", len(matched), conflicts)
    queries.write_countries(conn, matched, target_column="countries")
    return PhaseMetrics(seen=len(rows), new=len(matched), extras={"conflicts": conflicts})
