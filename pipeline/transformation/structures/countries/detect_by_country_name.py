"""Détection du pays d'une adresse par **nom de pays** en fin d'adresse : candidat `country_name`.

Confronte les derniers tokens du `normalized_text` de chaque adresse à traiter (`candidates_dirty`) aux noms de pays de `place_name_forms` (`kind = 'country'` : variantes anglais/français, codes ISO, abréviations), le plus long l'emportant. Un nom de pays clôt typiquement l'adresse, avec ou sans virgule ; les noms de lieux (institutions, villes) relèvent de la détection par nom de lieu. Le candidat `country_name` est recalculé en entier pour chaque adresse traitée.

Ne dépend que du port `CountryQueries` ; le commit est laissé au caller.
"""

import logging

from sqlalchemy import Connection

from domain.country_detection import CountryDetectionMethod
from pipeline.runtime.observability.libelles import BRANCHE, DERNIERE_BRANCHE, accord, etape
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.transformation.structures.countries.countries_queries import CountryQueries


def _match_trailing_country(
    normalized_text: str, country_forms: dict[str, str], max_tokens: int
) -> str | None:
    """Code ISO du plus long nom de pays qui termine `normalized_text`, ou None.

    Teste les suffixes de N tokens décroissants (N ≤ `max_tokens`) : le plus long l'emporte, de sorte qu'« united kingdom » prime sur « kingdom »."""
    tokens = normalized_text.split()
    for n in range(min(max_tokens, len(tokens)), 0, -1):
        iso = country_forms.get(" ".join(tokens[-n:]))
        if iso:
            return iso
    return None


def run(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> PhaseMetrics:
    """Ajoute le candidat `country_name` des adresses à traiter qui se terminent par un nom de pays.

    `seen` = adresses examinées, `new` = adresses qui reçoivent un candidat, `extras["unmatched"]` = adresses sans nom de pays final.
    """
    etape(logger, "Pays des adresses d'après le nom de pays qui les termine")
    country_forms = queries.load_country_forms(conn)
    max_tokens = max((form.count(" ") + 1 for form in country_forms), default=1)

    rows = queries.fetch_dirty_addresses_normalized(conn)
    logger.info("%s%s à traiter", BRANCHE, accord(len(rows), "adresse"))

    matched: list[tuple[int, list[str]]] = []
    for addr_id, normalized_text in rows:
        if iso := _match_trailing_country(normalized_text, country_forms, max_tokens):
            matched.append((addr_id, [iso]))

    added = queries.replace_candidates_of_dirty_addresses(
        conn, CountryDetectionMethod.COUNTRY_NAME, matched
    )
    logger.info("%spays trouvé pour %s", DERNIERE_BRANCHE, accord(added, "adresse"))
    return PhaseMetrics(seen=len(rows), new=added, extras={"unmatched": len(rows) - len(matched)})
