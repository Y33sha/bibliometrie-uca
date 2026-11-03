# STATUS: oneshot (2026-11-03)
"""Fusionne la publication d'un enregistrement source WoS sans DOI avec la publication d'un autre enregistrement source de même revue, même année et même première page.

WoS donne en anglais le titre des articles en d'autres langues. La réconciliation par titre manque donc ces articles. Une paire est retenue quand :

- l'enregistrement source WoS n'a aucun DOI actif, est seul dans sa publication, et a une revue, une année et une première page ;
- un enregistrement source d'une autre source, rattaché à une autre publication, a la même revue, la même année, la même première page, et la même dernière page si les deux la donnent ;
- ces enregistrements sources désignent une seule publication en face, sans enregistrement source WoS, visée par un seul enregistrement source WoS ;
- l'enregistrement source WoS partage un nom de famille normalisé avec un auteur de la publication en face.

Chaque fusion passe par la fusion manuelle de l'administration (`PublicationMergeService`), relue par la réconciliation à chaque exécution du pipeline. Elle est commitée seule. Une fusion refusée par le service est ignorée.

Usage :
    uv run python -m interfaces.cli.oneshot.merge_wos_without_doi            # exécution
    uv run python -m interfaces.cli.oneshot.merge_wos_without_doi --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import NamedTuple

from sqlalchemy import Connection, text

from domain.errors import NotFoundError, ValidationError
from infrastructure.db.engine import build_sync_engine
from infrastructure.observability.log import setup_logger
from interfaces.api.deps import publication_merge_service

log = setup_logger("merge_wos_without_doi", os.path.dirname(__file__))

_CANDIDATES_SQL = text("""
    WITH wos AS (
        SELECT sr.id, sr.source_id, sr.title, sr.publication_id, sr.serial_id,
               sr.publication_year, sr.biblio->>'first_page' AS first_page,
               nullif(sr.biblio->>'last_page', '') AS last_page
        FROM source_records sr
        WHERE sr.source = 'wos' AND sr.publication_id IS NOT NULL
          AND sr.serial_id IS NOT NULL AND sr.publication_year IS NOT NULL
          AND nullif(sr.biblio->>'first_page', '') IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM source_record_identifiers i
              WHERE i.source_record_id = sr.id AND i.id_type = 'doi'
                AND i.role <> 'related' AND i.removed_by IS NULL)
          AND NOT EXISTS (
              SELECT 1 FROM source_records o
              WHERE o.publication_id = sr.publication_id AND o.id <> sr.id)
    )
    SELECT DISTINCT w.id AS wos_id, w.source_id AS wos_source_id, w.title AS wos_title,
           w.publication_id AS wos_publication, o.publication_id AS other_publication,
           EXISTS (
               SELECT 1 FROM source_records ow
               WHERE ow.publication_id = o.publication_id AND ow.source = 'wos'
           ) AS other_has_wos,
           EXISTS (
               SELECT 1
               FROM source_contributions a
               JOIN contributor_information ai ON ai.id = a.contributor_information_id
               JOIN source_records b_sr ON b_sr.publication_id = o.publication_id
               JOIN source_contributions b ON b.source_record_id = b_sr.id
               JOIN contributor_information bi ON bi.id = b.contributor_information_id
               WHERE a.source_record_id = w.id
                 AND ai.last_name_normalized <> ''
                 AND ai.last_name_normalized = bi.last_name_normalized
           ) AS shared_author
    FROM wos w
    JOIN source_records o
      ON o.source <> 'wos' AND o.serial_id = w.serial_id
     AND o.publication_year = w.publication_year
     AND o.biblio->>'first_page' = w.first_page
     AND o.publication_id IS NOT NULL AND o.publication_id <> w.publication_id
     AND (w.last_page IS NULL OR nullif(o.biblio->>'last_page', '') IS NULL
          OR o.biblio->>'last_page' = w.last_page)
""")


class Pair(NamedTuple):
    """Publication d'un enregistrement source WoS sans DOI, et publication en face."""

    wos_source_id: str
    wos_title: str
    wos_publication: int
    other_publication: int


def find_pairs(conn: Connection) -> tuple[list[Pair], Counter[str]]:
    """Renvoie les paires à fusionner, et le décompte des enregistrements sources WoS écartés par motif."""
    candidates: dict[int, list] = defaultdict(list)
    for row in conn.execute(_CANDIDATES_SQL):
        candidates[row.wos_id].append(row)

    outcomes: Counter[str] = Counter()
    retained = []
    for rows in candidates.values():
        if len(rows) > 1:
            outcomes["plusieurs publications en face"] += 1
        elif rows[0].other_has_wos:
            outcomes["publication en face déjà présente dans WoS"] += 1
        elif not rows[0].shared_author:
            outcomes["aucun auteur commun"] += 1
        else:
            retained.append(rows[0])

    targets = Counter(row.other_publication for row in retained)
    pairs = []
    for row in retained:
        if targets[row.other_publication] > 1:
            outcomes["publication visée par plusieurs enregistrements WoS"] += 1
            continue
        pairs.append(
            Pair(row.wos_source_id, row.wos_title, row.wos_publication, row.other_publication)
        )
    return pairs, outcomes


def merge_pairs(conn: Connection, pairs: Iterable[Pair], *, apply: bool) -> Counter[str]:
    """Fusionne chaque paire, commite chaque fusion si `apply`, et renvoie le décompte des issues."""
    outcomes: Counter[str] = Counter()
    merges = publication_merge_service(conn)
    for pair in pairs:
        savepoint = conn.begin_nested()
        try:
            outcome = merges.merge(pair.wos_publication, pair.other_publication)
        except (ValidationError, NotFoundError) as e:
            savepoint.rollback()
            log.warning("%s → %s : %s", pair.wos_source_id, pair.other_publication, e)
            outcomes["fusion refusée"] += 1
            continue
        savepoint.commit()
        if apply:
            conn.commit()
        log.info(
            "%s « %s » → publication %s",
            pair.wos_source_id,
            pair.wos_title,
            outcome.publication_id,
        )
        outcomes["fusionnées"] += 1
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    apply = not args.dry_run
    # Le rôle de l'API écrit les fusions manuelles.
    with build_sync_engine("app").connect() as conn:
        pairs, outcomes = find_pairs(conn)
        outcomes += merge_pairs(conn, pairs, apply=apply)
        if not apply:
            conn.rollback()
    for label, n in outcomes.most_common():
        log.info("%s : %d", label, n)
    log.info("✓ fusions appliquées" if apply else "DRY-RUN — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
