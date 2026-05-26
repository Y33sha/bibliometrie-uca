# STATUS: oneshot (2026-05-26)
"""
Audit (pure lecture) : combien de publishers locaux sans `country`
(après Phase 2 OpenAlex Publishers) pourraient en gagner un via le
champ `location` retourné par l'API Crossref Members ?

Sert à décider si Phase 5 (`enrich_publishers_from_crossref_members`)
vaut le détour, ou si la couverture OpenAlex actuelle suffit.

Pipeline d'extraction :
1. Pour chaque publisher local sans country mais avec ≥ 1
   `doi_prefixes.crossref_member_id`, fetcher
   `api.crossref.org/members/{id}`
2. Parser `location` (texte libre style "Amsterdam, NX, Netherlands")
   → dernier élément = nom du pays
3. Normaliser et chercher dans `country_name_forms` pour obtenir
   l'ISO-2

Ne fait AUCUNE écriture en base.

Usage :
    python -m interfaces.cli.oneshot.audit_crossref_member_countries [--limit N]
"""

from __future__ import annotations

import argparse
import os
import time
from collections import Counter, defaultdict
from typing import Any

import requests
from sqlalchemy import text

from domain.normalize import normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.api_limits import CROSSREF_DELAY
from infrastructure.sources.config import get_polite_pool_email

log = setup_logger("audit_crossref_member_countries", os.path.dirname(__file__))

CROSSREF_MEMBER_URL = "https://api.crossref.org/members/{id}"


def fetch_member(member_id: int, *, mailto: str) -> dict[str, Any] | None:
    """GET sur api.crossref.org/members/{id}. Retourne le message ou None."""
    try:
        resp = requests.get(
            CROSSREF_MEMBER_URL.format(id=member_id),
            params={"mailto": mailto},
            timeout=15,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        body = resp.json()
        msg = body.get("message")
        return msg if isinstance(msg, dict) else None
    except requests.RequestException as e:
        log.warning("Crossref fetch failed for member %d : %s", member_id, e)
        return None


def parse_country_from_location(location: str) -> str:
    """Extrait le dernier segment d'une 'City, State, Country'."""
    parts = [p.strip() for p in location.split(",") if p.strip()]
    return parts[-1] if parts else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limiter le nombre de publishers audités (0 = tous)",
    )
    args = parser.parse_args()

    engine = get_sync_engine()
    with engine.connect() as conn:
        mailto = get_polite_pool_email(conn)

        sql = """
            SELECT
                p.id, p.name,
                (SELECT MIN(dp.crossref_member_id)
                 FROM doi_prefixes dp
                 WHERE dp.publisher_id = p.id
                   AND dp.crossref_member_id IS NOT NULL
                ) AS member_id
            FROM publishers p
            WHERE p.country IS NULL
              AND EXISTS (
                  SELECT 1 FROM doi_prefixes dp2
                  WHERE dp2.publisher_id = p.id
                    AND dp2.crossref_member_id IS NOT NULL
              )
            ORDER BY p.id
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        rows = conn.execute(text(sql)).all()
        total = len(rows)
        log.info(
            "%d publishers candidats (sans country, avec crossref_member_id via doi_prefixes)",
            total,
        )
        if total == 0:
            return 0

        cnf_rows = conn.execute(
            text("SELECT form_normalized, iso_code FROM country_name_forms")
        ).all()
        country_map: dict[str, str] = {r.form_normalized: r.iso_code for r in cnf_rows}
        log.info("Mapping country_name_forms : %d formes connues", len(country_map))

        no_record = 0
        no_location = 0
        no_match = 0
        mapped = 0
        country_counter: Counter[str] = Counter()
        unmatched_raw: Counter[str] = Counter()
        samples_by_country: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
        unmatched_samples: list[tuple[int, str, str]] = []

        for i, row in enumerate(rows, 1):
            member = fetch_member(row.member_id, mailto=mailto)
            time.sleep(CROSSREF_DELAY)
            if member is None:
                no_record += 1
                continue
            location = member.get("location", "") or ""
            if not location:
                no_location += 1
                continue
            country_raw = parse_country_from_location(location)
            country_norm = normalize_text(country_raw)
            iso = country_map.get(country_norm) if country_norm else None
            if iso is None:
                no_match += 1
                unmatched_raw[country_raw] += 1
                if len(unmatched_samples) < 10:
                    unmatched_samples.append((row.id, row.name, location))
                continue
            mapped += 1
            country_counter[iso] += 1
            if len(samples_by_country[iso]) < 3:
                samples_by_country[iso].append((row.id, row.name, location))

            if i % 50 == 0:
                log.info("  %d/%d fetchés", i, total)

        log.info("─" * 70)
        log.info("Bilan sur %d publishers candidats :", total)
        log.info("  mapped       : %d  (country posable via Crossref)", mapped)
        log.info("  no_match     : %d  (pays brut non mappé dans country_name_forms)", no_match)
        log.info("  no_location  : %d  (Crossref ne renvoie pas de location)", no_location)
        log.info("  no_record    : %d  (Crossref member 404 ou erreur)", no_record)
        log.info("─" * 70)
        if country_counter:
            log.info("Top 10 pays posables :")
            for iso, n in country_counter.most_common(10):
                log.info("  %s  %d", iso, n)
        if unmatched_raw:
            log.info("─" * 70)
            log.info("Top 10 pays bruts non mappés (= forme absente de country_name_forms) :")
            for raw, n in unmatched_raw.most_common(10):
                log.info("  %-40s %d", raw, n)
            log.info("Exemples no_match (publisher → location) :")
            for pub_id, name, loc in unmatched_samples[:5]:
                log.info("  #%d %s → '%s'", pub_id, name, loc)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
