"""SQL pour les liens personne ↔ `source_authorships` et les authorships vérité."""

from typing import Any

from sqlalchemy import text

from domain.sources import (
    AUTHOR_SOURCES_SQL,
    SOURCE_PRIORITY,
    SOURCE_PRIORITY_IS_CORRESPONDING,
    source_case_sql,
)
from infrastructure.repositories.person_repository import _name_forms


def link_authorship(
    conn: Any,
    person_id: int,
    source: str,
    authorship_id: int,
    *,
    source_person_id: int | None = None,
    has_hal_person_id: bool = False,
) -> None:
    """Rattache une authorship source à une personne.

    Pour HAL avec un compte HAL, propage aussi le person_id vers
    source_persons (dual-write attendu par l'étape 0 du pipeline).
    """
    conn.execute(
        text("UPDATE source_authorships SET person_id = :pid WHERE id = :aid AND source = :src"),
        {"pid": person_id, "aid": authorship_id, "src": source},
    )
    if source == "hal" and source_person_id and has_hal_person_id:
        conn.execute(
            text("""
                UPDATE source_persons SET person_id = :pid
                WHERE id = :sp
                  AND (source_ids->>'hal_person_id') IS NOT NULL
            """),
            {"pid": person_id, "sp": source_person_id},
        )


def unlink_authorship(conn: Any, person_id: int, source: str, authorship_id: int) -> None:
    conn.execute(
        text("""
            UPDATE source_authorships SET person_id = NULL
            WHERE id = :aid AND person_id = :pid AND source = :src
        """),
        {"aid": authorship_id, "pid": person_id, "src": source},
    )


def assign_orphan_sa(conn: Any, person_id: int, source: str, authorship_id: int) -> dict | None:
    """Tente de poser person_id sur une source_authorship orpheline.

    Retourne un dict {excluded, author_name_normalized} si l'UPDATE a
    touché une ligne, None si déjà attribuée à une autre personne.
    """
    row = conn.execute(
        text("""
            UPDATE source_authorships SET person_id = :pid
            WHERE id = :aid AND source = :src AND person_id IS NULL
            RETURNING excluded, author_name_normalized
        """),
        {"pid": person_id, "aid": authorship_id, "src": source},
    ).first()
    return dict(row._mapping) if row else None


def batch_assign_orphans(conn: Any, person_id: int, sa_ids: list[int]) -> int:
    """Rattache en batch un lot de source_authorships orphelines, crée les
    authorships vérité manquantes, pose les FK et ajoute les formes de noms.

    Retourne le nombre de source_authorships réellement rattachées.
    """
    if not sa_ids:
        return 0

    # 1. Rattacher les source_authorships orphelines
    assigned = conn.execute(
        text("""
            UPDATE source_authorships SET person_id = :pid
            WHERE id = ANY(:ids) AND person_id IS NULL
            RETURNING id
        """),
        {"pid": person_id, "ids": sa_ids},
    ).rowcount

    # 2. Créer les authorships vérité manquantes
    conn.execute(
        text(f"""
            INSERT INTO authorships (publication_id, person_id,
                author_position, in_perimeter, is_corresponding, structure_ids)
            SELECT DISTINCT ON (sd.publication_id)
                sd.publication_id, :pid,
                sa.author_position, sa.in_perimeter, sa.is_corresponding, sa.structure_ids
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.id = ANY(:ids) AND sd.publication_id IS NOT NULL
            ORDER BY sd.publication_id, {source_case_sql(SOURCE_PRIORITY)}
            ON CONFLICT (publication_id, person_id) DO NOTHING
        """),
        {"pid": person_id, "ids": sa_ids},
    )

    # 3. Poser les FK authorship_id sur les source_authorships
    conn.execute(
        text("""
            UPDATE source_authorships sa SET authorship_id = a.id
            FROM source_publications sd, authorships a
            WHERE sa.id = ANY(:ids)
              AND sd.id = sa.source_publication_id
              AND a.publication_id = sd.publication_id
              AND a.person_id = :pid
              AND sa.authorship_id IS NULL
        """),
        {"ids": sa_ids, "pid": person_id},
    )

    # 4. Récupérer les formes de nom observées et les ajouter
    rows = conn.execute(
        text("""
            SELECT DISTINCT author_name_normalized
            FROM source_authorships
            WHERE id = ANY(:ids)
              AND author_name_normalized IS NOT NULL
              AND NOT excluded
        """),
        {"ids": sa_ids},
    ).all()
    for row in rows:
        _name_forms.add_name_form(conn, person_id, row.author_name_normalized)

    return assigned


def ensure_truth_authorship(conn: Any, person_id: int, source: str, authorship_id: int) -> None:
    """Crée/synchronise l'authorship vérité pour une paire (pub, person).

    Même logique que build_authorships.py mais pour une seule paire :
    FK sources, author_position, is_corresponding, in_perimeter,
    structure_ids — agrégés depuis les source_authorships.
    """
    pub_id = conn.execute(
        text("""
            SELECT d.publication_id FROM source_authorships sa
            JOIN source_publications d ON d.id = sa.source_publication_id
            WHERE sa.id = :aid AND sa.source = :src
        """),
        {"aid": authorship_id, "src": source},
    ).scalar_one_or_none()
    if not pub_id:
        return

    # 1. INSERT si pas déjà existant
    conn.execute(
        text("""
            INSERT INTO authorships (publication_id, person_id)
            VALUES (:pub, :pid)
            ON CONFLICT (publication_id, person_id) DO NOTHING
        """),
        {"pub": pub_id, "pid": person_id},
    )

    # 2. FK sources (source_authorships.authorship_id → authorships.id)
    conn.execute(
        text("""
            UPDATE source_authorships sa
            SET authorship_id = a.id
            FROM source_publications sd, authorships a
            WHERE sd.id = sa.source_publication_id
              AND a.publication_id = sd.publication_id
              AND a.person_id = sa.person_id
              AND sd.publication_id = :pub
              AND sa.person_id = :pid
              AND NOT sa.excluded
              AND sa.authorship_id IS NULL
        """),
        {"pub": pub_id, "pid": person_id},
    )

    # 3. author_position et is_corresponding
    conn.execute(
        text(f"""
            UPDATE authorships a
            SET author_position = sub.pos,
                is_corresponding = COALESCE(a.is_corresponding, sub.corr)
            FROM (
                SELECT sa.authorship_id,
                       (array_agg(sa.author_position ORDER BY
                           {source_case_sql(SOURCE_PRIORITY)}
                       ))[1] AS pos,
                       (array_agg(sa.is_corresponding ORDER BY
                           {source_case_sql(SOURCE_PRIORITY_IS_CORRESPONDING)}
                       ))[1] AS corr
                FROM source_authorships sa
                WHERE sa.authorship_id IS NOT NULL AND NOT sa.excluded
                GROUP BY sa.authorship_id
            ) sub
            WHERE a.id = sub.authorship_id
              AND a.publication_id = :pub AND a.person_id = :pid
        """),
        {"pub": pub_id, "pid": person_id},
    )

    # 4. in_perimeter et structure_ids (union des sources)
    conn.execute(
        text(f"""
            WITH src AS (
                SELECT sa.in_perimeter AS uca, sa.structure_ids AS sids
                FROM source_authorships sa
                JOIN source_publications sd ON sd.id = sa.source_publication_id
                WHERE sa.source IN {AUTHOR_SOURCES_SQL}
                  AND sd.publication_id = :pub AND sa.person_id = :pid AND NOT sa.excluded
            ),
            agg AS (
                SELECT bool_or(uca) AS in_perimeter,
                       array_agg(DISTINCT sid) FILTER (WHERE sid IS NOT NULL) AS all_sids
                FROM src, LATERAL unnest(COALESCE(sids, '{{}}'::int[])) AS sid
            )
            UPDATE authorships a
            SET in_perimeter = COALESCE(agg.in_perimeter, FALSE),
                structure_ids = NULLIF(agg.all_sids, ARRAY[]::int[]),
                updated_at = now()
            FROM agg
            WHERE a.publication_id = :pub AND a.person_id = :pid
        """),
        {"pub": pub_id, "pid": person_id},
    )


def count_authorships_with_name_form(conn: Any, person_id: int, name_form: str) -> int:
    """Compte les source_authorships actives d'une personne portant une
    forme de nom donnée. Utilisé par detach_authorships pour décider
    de nettoyer la name_form ou pas."""
    return conn.execute(
        text(f"""
            SELECT COUNT(*) AS n FROM source_authorships sa
            WHERE sa.person_id = :pid AND sa.author_name_normalized = :nf
              AND sa.source IN {AUTHOR_SOURCES_SQL}
        """),
        {"pid": person_id, "nf": name_form},
    ).scalar_one()
