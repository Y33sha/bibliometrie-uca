"""Détection du pays d'une adresse par **nom de pays**.

Parse le dernier segment (après la dernière virgule) de chaque adresse sans pays et le matche contre les noms de pays de `place_name_forms` (`kind = 'country'` : variantes anglais/français, codes ISO, abréviations). Un nom de pays y figure typiquement en fin de segment ; les noms de lieux (institutions, villes) relèvent de la détection par nom de lieu. Écriture directe dans `addresses.countries` (confiance élevée), qui marque aussi `countries_dirty` pour le recalcul aval.

Ne dépend que du port `CountryQueries` et du domaine ; le commit est laissé au caller.
"""

import logging

from sqlalchemy import Connection

from application.pipeline.metrics import PhaseMetrics
from application.ports.pipeline.countries import CountryQueries
from domain.normalize import normalize_text


def _last_segment(raw_text: str) -> str:
    """Dernier segment normalisé après la dernière virgule (l'adresse entière si aucune virgule)."""
    last, _, tail = raw_text.rpartition(",")
    return normalize_text((tail if last else raw_text).strip())


def run(conn: Connection, queries: CountryQueries, logger: logging.Logger) -> PhaseMetrics:
    """Détecte le pays des adresses sans pays via le nom de pays du dernier segment.

    `seen` = adresses sans pays, `new` = adresses matchées et écrites, `extras["unmatched"]` = sans correspondance.
    """
    country_forms = queries.load_country_forms(conn)
    logger.info("%d formes de noms de pays chargées", len(country_forms))

    rows = queries.fetch_addresses_missing_country_raw(conn)
    logger.info("%d adresses sans pays", len(rows))

    matched: list[tuple[int, list[str]]] = []
    unmatched = 0
    for addr_id, raw_text in rows:
        segment = _last_segment(raw_text)
        iso = country_forms.get(segment) if segment else None
        if iso:
            matched.append((addr_id, [iso]))
        else:
            unmatched += 1

    logger.info("Matchés : %d, non matchés : %d", len(matched), unmatched)
    queries.write_countries(conn, matched, target_column="countries")
    return PhaseMetrics(seen=len(rows), new=len(matched), extras={"unmatched": unmatched})
