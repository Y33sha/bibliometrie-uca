"""Détection du pays d'une adresse par **nom de pays** en fin d'adresse.

Confronte les derniers tokens du `normalized_text` de chaque adresse sans pays aux noms de pays de `place_name_forms` (`kind = 'country'` : variantes anglais/français, codes ISO, abréviations), le plus long l'emportant. Un nom de pays clôt typiquement l'adresse, avec ou sans virgule ; les noms de lieux (institutions, villes) relèvent de la détection par nom de lieu. Écriture directe dans `addresses.countries` (confiance élevée), qui marque aussi `countries_dirty` pour le recalcul aval.

Ne dépend que du port `CountryQueries` ; le commit est laissé au caller.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.countries import CountryQueries


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
    """Détecte le pays des adresses sans pays via le nom de pays qui les termine.

    `seen` = adresses sans pays, `new` = adresses matchées et écrites, `extras["unmatched"]` = sans correspondance.
    """
    country_forms = queries.load_country_forms(conn)
    max_tokens = max((form.count(" ") + 1 for form in country_forms), default=1)
    logger.info("%d formes de noms de pays chargées", len(country_forms))

    rows = queries.fetch_addresses_missing_country_normalized(conn)
    logger.info("%d adresses sans pays", len(rows))

    matched: list[tuple[int, list[str]]] = []
    unmatched = 0
    for addr_id, normalized_text in rows:
        iso = _match_trailing_country(normalized_text, country_forms, max_tokens)
        if iso:
            matched.append((addr_id, [iso]))
        else:
            unmatched += 1

    logger.info("Matchés : %d, non matchés : %d", len(matched), unmatched)
    queries.write_countries(conn, matched, target_column="countries")
    return PhaseMetrics(seen=len(rows), new=len(matched), extras={"unmatched": unmatched})
