# STATUS: oneshot (2026-05-26)
"""
Audit (pure lecture) : pour les publishers locaux qui ont un `ror`
non-NULL, fetcher leur enregistrement ROR et reporter la distribution
des combinaisons de `types` (ROR v2 expose `types` comme une LISTE,
ex. `['company', 'funder']`).

Sert à figer le mapping ROR `types` → notre `publisher_type` (Phase 3
de docs/chantiers/METIER_pipeline-publishers-journals.md), en particulier
pour les cas litigieux (`nonprofit`, combinaisons multiples).

Ne fait AUCUNE écriture en base.

Usage :
    python -m interfaces.cli.oneshot.audit_ror_types_for_publishers [--limit N]
"""

from __future__ import annotations

import argparse
import os
import time
from collections import defaultdict
from typing import Any

import requests
from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.sources.config import get_polite_pool_email

log = setup_logger("audit_ror_types_for_publishers", os.path.dirname(__file__))

ROR_API = "https://api.ror.org/v2/organizations/{ror}"
RATE_DELAY = 0.1  # 10 req/s, bien sous la limite ROR (~6.66 req/s sustained)


# Mapping candidat — à valider via l'audit. Ordre de précédence : le
# premier match dans cet ordre l'emporte (un publisher ROR `['education',
# 'funder']` matche `education` → academic_institution, pas funder).
_CANDIDATE_MAPPING: list[tuple[str, str]] = [
    ("education", "academic_institution"),
    ("government", "academic_institution"),
    ("archive", "repository"),
    ("company", "commercial"),
    ("nonprofit", "learned_society"),  # à arbitrer après audit
    # `funder`, `healthcare`, `facility`, `other` → laissés non-mappés
]


def map_ror_types(ror_types: list[str]) -> str | None:
    """Applique le mapping candidat. None = aucun match (= ne pas écrire)."""
    for ror_type, publisher_type in _CANDIDATE_MAPPING:
        if ror_type in ror_types:
            return publisher_type
    return None


def fetch_ror_record(ror: str, *, user_agent: str) -> dict[str, Any] | None:
    """GET sur l'API ROR v2. Retourne None sur 404 ou erreur. Pas de retry
    élaboré — c'est un audit, pas un job critique."""
    try:
        resp = requests.get(
            ROR_API.format(ror=ror),
            headers={"User-Agent": user_agent},
            timeout=15,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        log.warning("ROR fetch failed for %s : %s", ror, e)
        return None


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
        email = get_polite_pool_email(conn)
        user_agent = f"bibliometrie-uca-audit/1.0 (mailto:{email})"

        sql = """
            SELECT id, name, ror
            FROM publishers
            WHERE ror IS NOT NULL
            ORDER BY id
        """
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        rows = conn.execute(text(sql)).all()
        total = len(rows)
        log.info("%d publishers avec un ROR à auditer.", total)

        if total == 0:
            log.info("Rien à faire.")
            return 0

        # tuple de types → liste de (publisher_id, name, ror)
        by_types: dict[tuple[str, ...], list[tuple[int, str, str]]] = defaultdict(list)
        no_record = 0
        no_types = 0

        for i, row in enumerate(rows, 1):
            record = fetch_ror_record(row.ror, user_agent=user_agent)
            time.sleep(RATE_DELAY)
            if record is None:
                no_record += 1
                continue
            types = record.get("types") or []
            if not types:
                no_types += 1
                continue
            key = tuple(sorted(types))
            by_types[key].append((row.id, row.name, row.ror))
            if i % 50 == 0:
                log.info("  %d/%d records ROR fetchés", i, total)

        log.info("─" * 70)
        log.info("Distribution des combinaisons ROR `types` :")
        # Trie par effectif décroissant
        sorted_types = sorted(by_types.items(), key=lambda kv: -len(kv[1]))
        for type_tuple, pubs in sorted_types:
            type_label = "+".join(type_tuple)
            mapping = map_ror_types(list(type_tuple))
            mapping_label = mapping if mapping else "(non mappé)"
            log.info(
                "  %-35s %4d publishers  → %s",
                type_label,
                len(pubs),
                mapping_label,
            )
        log.info("─" * 70)
        log.info("Sans record ROR (404 ou erreur) : %d", no_record)
        log.info("Avec record mais sans `types` : %d", no_types)
        log.info("─" * 70)
        log.info("Exemples par combinaison (max 3 par bucket) :")
        for type_tuple, pubs in sorted_types:
            type_label = "+".join(type_tuple)
            log.info("  [%s]", type_label)
            for pub_id, name, ror in pubs[:3]:
                log.info("    #%d %s (ror=%s)", pub_id, name, ror)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
