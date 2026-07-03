# STATUS: oneshot (2026-05-30)
"""Audit (pure lecture) : sources auxquelles il manque un `person_id`
sur des authorships dont une autre source est déjà rattachée à un
person canonique, à la même position.

Cible le sujet `METIER_authorships-cross-source-matching` (chantier en cours,
cf. `docs/chantiers/`). Sert à mesurer le volume et à qualifier à l'œil
le taux de vrais positifs avant un éventuel oneshot d'application.

Deux sorties :

1. **Compteurs par source manquante** : total des SA orphelines avec
   position-match, dont nombre où `author_name_normalized` est strictement
   identique au nom de la SA déjà liée (proxy d'un matching trivial).
2. **Échantillon ~20 cas par source** : publi + position + nom de la SA
   de référence + nom de l'orpheline, pour validation visuelle.

Ne fait AUCUNE écriture en base.

Usage :
    python -m interfaces.cli.oneshot.audit_authorships_cross_source
"""

from __future__ import annotations

import os

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("audit_authorships_cross_source", os.path.dirname(__file__))


_ORPHANS_CTE = """
    WITH linked AS (
        SELECT a.id AS authorship_id, a.publication_id, a.person_id, a.author_position
        FROM authorships a
        WHERE a.person_id IS NOT NULL AND a.author_position IS NOT NULL
    ),
    -- Max d'auteurs par publication (MAX parmi les sources, comme
    -- `_max_authors_per_pub` côté Python). Sert au filtre méga-papers
    -- aligné sur `MAX_AUTHORS_CROSS_SOURCE = 50` de la cascade existante :
    -- au-delà, les positions divergent entre sources et le matching
    -- (pub, position) cesse d'être discriminant.
    pub_max_authors AS (
        SELECT publication_id, MAX(per_source_count) AS max_authors
        FROM (
            SELECT sp.publication_id, sp.source, COUNT(*) AS per_source_count
            FROM source_publications sp
            JOIN source_authorships sa ON sa.source_publication_id = sp.id
            GROUP BY sp.publication_id, sp.source
        ) per_source
        GROUP BY publication_id
    ),
    -- Un nom de référence par authorship canonique : on prend la première
    -- SA liée (ordre source, source_id) — peu importe laquelle, c'est juste
    -- un proxy de "comment l'auteur est nommé" pour comparaison.
    reference_name AS (
        SELECT DISTINCT ON (sa.authorship_id)
               sa.authorship_id,
               sa.raw_author_name AS ref_raw,
               aik.author_name_normalized AS ref_norm
        FROM source_authorships sa
        JOIN author_identifying_keys aik ON aik.id = sa.identity_id
        WHERE sa.authorship_id IS NOT NULL
          AND aik.author_name_normalized IS NOT NULL
        ORDER BY sa.authorship_id, sa.source, sa.id
    ),
    orphans AS (
        SELECT linked.publication_id,
               linked.author_position,
               linked.authorship_id,
               linked.person_id,
               other_sa.id AS orphan_sa_id,
               other_sa.source AS missing_source,
               other_sa.raw_author_name AS orphan_raw,
               other_aik.author_name_normalized AS orphan_norm,
               ref.ref_raw,
               ref.ref_norm,
               pub_max_authors.max_authors AS pub_max_authors
        FROM linked
        JOIN pub_max_authors ON pub_max_authors.publication_id = linked.publication_id
        JOIN source_publications sp_other ON sp_other.publication_id = linked.publication_id
        JOIN source_authorships other_sa
            ON other_sa.source_publication_id = sp_other.id
           AND other_sa.author_position = linked.author_position
           AND other_sa.person_id IS NULL
           AND other_sa.raw_author_name IS NOT NULL
        JOIN author_identifying_keys other_aik ON other_aik.id = other_sa.identity_id
        JOIN reference_name ref ON ref.authorship_id = linked.authorship_id
    )
"""

_COUNTS_SQL = (
    _ORPHANS_CTE
    + """
    SELECT
        missing_source,
        COUNT(DISTINCT orphan_sa_id) AS total,
        COUNT(DISTINCT orphan_sa_id) FILTER (WHERE orphan_norm = ref_norm) AS same_name,
        COUNT(DISTINCT orphan_sa_id) FILTER (WHERE pub_max_authors <= 50) AS small_pubs,
        COUNT(DISTINCT orphan_sa_id) FILTER (
            WHERE pub_max_authors <= 50 AND orphan_norm = ref_norm
        ) AS small_pubs_same_name
    FROM orphans
    GROUP BY missing_source
    ORDER BY total DESC;
"""
)

_SAMPLE_SQL = (
    _ORPHANS_CTE
    + """
    SELECT publication_id, author_position, person_id,
           ref_raw, orphan_raw,
           (orphan_norm = ref_norm) AS same_norm
    FROM orphans
    WHERE missing_source = :source
      AND pub_max_authors <= 50
    ORDER BY random()
    LIMIT 20;
"""
)


def main() -> int:
    engine = get_sync_engine()
    with engine.connect() as conn:
        log.info("=== Compteurs par source manquante ===")
        log.info(
            f"{'source':10s} {'total':>8s} {'same_name':>10s} {'≤50 auth':>10s} {'≤50 & same':>12s}"
        )
        sources_with_data: list[str] = []
        for row in conn.execute(text(_COUNTS_SQL)).all():
            log.info(
                f"{row.missing_source:10s} {row.total:8d} {row.same_name:10d}"
                f" {row.small_pubs:10d} {row.small_pubs_same_name:12d}"
            )
            sources_with_data.append(row.missing_source)

        log.info("")
        log.info("(Filtre `≤50 auth` = max d'auteurs par source ≤ 50,")
        log.info(" cohérent avec MAX_AUTHORS_CROSS_SOURCE de la cascade.)")

        for source in sources_with_data:
            log.info("")
            log.info(f"=== Échantillon {source} (≤20, méga-papers exclus) ===")
            samples = conn.execute(text(_SAMPLE_SQL), {"source": source}).all()
            for s in samples:
                flag = "=" if s.same_norm else "≠"
                log.info(
                    f"  pub={s.publication_id:>7d} pos={s.author_position:>2d} "
                    f"person={s.person_id:>7d}  ref='{s.ref_raw}'  {flag}  orphan='{s.orphan_raw}'"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
