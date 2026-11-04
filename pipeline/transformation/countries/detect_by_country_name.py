"""Détection du pays d'une adresse par **nom de pays** en fin d'adresse : candidat `country_name`.

Confronte les derniers tokens du `normalized_text` de chaque adresse en file (`address_candidates_queue`) aux noms de pays de `place_name_forms` (`kind = 'country'` : variantes anglais/français, codes ISO, abréviations), le plus long l'emportant. Le candidat `country_name` est recalculé en entier pour chaque adresse traitée. L'appelant commite.
"""

import logging

from sqlalchemy import Connection

from domain.addresses.country_detection import CountryDetectionMethod
from pipeline.runtime.observability.log_format import BRANCH, LAST_BRANCH, quantity, step
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.countries.place_names import load_country_names
from pipeline.transformation.countries.store import CountryCandidatesStore


def run(conn: Connection, logger: logging.Logger) -> PhaseMetrics:
    """Ajoute le candidat `country_name` des adresses à traiter qui se terminent par un nom de pays.

    `seen` = adresses examinées, `new` = adresses qui reçoivent un candidat, `extras["unmatched"]` = adresses sans nom de pays final.
    """
    step(logger, "Pays des adresses d'après le nom de pays qui les termine")
    store = CountryCandidatesStore(conn)
    country_names = load_country_names(conn)

    rows = store.queued_addresses()
    logger.info("%s%s à traiter", BRANCH, quantity(len(rows), "adresse"))

    matched: list[tuple[int, list[str]]] = []
    for addr_id, normalized_text in rows:
        if iso := country_names.trailing_country(normalized_text):
            matched.append((addr_id, [iso]))

    added = store.replace_for_queued_addresses(CountryDetectionMethod.COUNTRY_NAME, matched)
    logger.info("%spays trouvé pour %s", LAST_BRANCH, quantity(added, "adresse"))
    return PhaseMetrics(seen=len(rows), new=added, extras={"unmatched": len(rows) - len(matched)})
