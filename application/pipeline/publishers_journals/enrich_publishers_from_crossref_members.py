"""
Sub-step de la phase pipeline `publishers_journals` — fallback
`publishers.country` via l'API Crossref Members pour les éditeurs sans
country (= manqués par OpenAlex Publishers en Phase 2).

Pour chaque publisher avec `country IS NULL` + au moins un
`doi_prefixes.crossref_member_id` :
1. Fetche `api.crossref.org/members/{id}` (via le `CrossrefMemberFetcher`
   injecté par la composition root).
2. Parse `location` (texte libre) → dernier segment = nom du pays via
   `domain.publishers.crossref_location.parse_country_segment`.
3. Résout le nom du pays en ISO-2 via la table `country_name_forms`
   (mapping chargé en bloc au démarrage).
4. Écrit `publishers.country` si résolu — politique « NULL only »
   garantie par le filtre côté query.

Audit `audit_crossref_member_countries` a montré ~95% de couverture
sur les candidats (1162 / 1219). Les 4.6% de `no_match` sont des
locations dégénérées (Crossref ne met pas le pays au bout, ou forme
absente de `country_name_forms`).

Le fetcher concret vit dans `infrastructure/sources/crossref/members.py` ;
il est injecté par la composition root pour respecter l'étanchéité DDD.
"""

import logging
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, text

from application.ports.pipeline.enrich import EnrichQueries
from application.ports.repositories.publisher_repository import (
    PublisherRepository,
    PublisherUpdateFields,
)
from domain.normalize import normalize_text
from domain.publishers.crossref_location import parse_country_segment

type CrossrefMemberFetcher = Callable[[int], dict[str, Any] | None]
"""Signature : ``(member_id) → record `message` ou None (404 / erreur)``."""

COMMIT_EVERY = 50


def run_enrich_publishers_from_crossref_members(
    conn: Connection,
    queries: EnrichQueries,
    logger: logging.Logger,
    *,
    publisher_repo: PublisherRepository,
    fetcher: CrossrefMemberFetcher,
    limit: int = 0,
    dry_run: bool = False,
    rate_delay: float = 0.1,
) -> None:
    try:
        candidates = queries.fetch_publishers_needing_country_from_crossref(
            conn, limit=limit or None
        )
        total = len(candidates)
        logger.info(f"{total} publishers candidats (country IS NULL avec crossref_member_id).")

        if total == 0:
            logger.info("Rien à faire.")
            return

        # Charger le mapping nom-pays → ISO-2 une fois (la table contient
        # quelques centaines de formes au plus).
        country_map_rows = conn.execute(
            text("SELECT form_normalized, iso_code FROM country_name_forms")
        ).all()
        country_map: dict[str, str] = {r.form_normalized: r.iso_code for r in country_map_rows}
        logger.info("country_name_forms : %d formes connues", len(country_map))

        mapped_count = 0
        no_match = 0
        no_location = 0
        no_record = 0
        country_counter: Counter[str] = Counter()
        unmatched_raw: Counter[str] = Counter()

        for i, (publisher_id, member_id) in enumerate(candidates, 1):
            member = fetcher(member_id)
            time.sleep(rate_delay)
            if member is None:
                no_record += 1
                continue
            location_raw = member.get("location", "")
            location = location_raw if isinstance(location_raw, str) else ""
            if not location:
                no_location += 1
                continue
            country_raw = parse_country_segment(location)
            if country_raw is None:
                no_location += 1
                continue
            country_norm = normalize_text(country_raw)
            iso = country_map.get(country_norm) if country_norm else None
            if iso is None:
                no_match += 1
                unmatched_raw[country_raw] += 1
                continue

            if not dry_run:
                publisher_repo.update_publisher_fields(
                    publisher_id, PublisherUpdateFields(country=iso)
                )
            mapped_count += 1
            country_counter[iso] += 1

            if not dry_run and i % COMMIT_EVERY == 0:
                conn.commit()
                logger.info(f"  {i}/{total} traités, {mapped_count} countries posés")

        if not dry_run:
            conn.commit()

        logger.info(
            f"Terminé : {mapped_count}/{total} publishers ont gagné un country "
            f"({no_match} pays brut non mappé, {no_location} sans location "
            f"exploitable, {no_record} sans record Crossref)."
        )
        if country_counter:
            distrib = ", ".join(f"{iso}={n}" for iso, n in country_counter.most_common(10))
            logger.info("Top 10 countries posés : %s", distrib)
        if unmatched_raw:
            top = ", ".join(f"{raw}={n}" for raw, n in unmatched_raw.most_common(5))
            logger.info(
                "Top 5 country bruts non mappés (à enrichir dans country_name_forms si volume justifie) : %s",
                top,
            )

    except KeyboardInterrupt:
        if not dry_run:
            conn.commit()
        logger.warning("Interruption — données déjà traitées conservées.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur fatale : {e}")
        raise
