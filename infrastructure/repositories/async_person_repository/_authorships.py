"""SQL async pour les liens personne ↔ source_authorships et les authorships vérité."""

from typing import Any

from domain.sources import AUTHOR_SOURCES_SQL
from infrastructure.db_helpers import row_val as _val
from infrastructure.repositories.async_person_repository import _name_forms


async def link_authorship(
    cur: Any,
    person_id: int,
    source: str,
    authorship_id: int,
    *,
    source_person_id: int | None = None,
    has_hal_person_id: bool = False,
) -> None:
    await cur.execute(
        "UPDATE source_authorships SET person_id = %s WHERE id = %s AND source = %s",
        (person_id, authorship_id, source),
    )
    if source == "hal" and source_person_id and has_hal_person_id:
        await cur.execute(
            """
            UPDATE source_persons SET person_id = %s
            WHERE id = %s AND (source_ids->>'hal_person_id') IS NOT NULL
            """,
            (person_id, source_person_id),
        )


async def unlink_authorship(
    cur: Any, person_id: int, source: str, authorship_id: int
) -> None:
    await cur.execute(
        """
        UPDATE source_authorships SET person_id = NULL
        WHERE id = %s AND person_id = %s AND source = %s
        """,
        (authorship_id, person_id, source),
    )


async def assign_orphan_sa(
    cur: Any, person_id: int, source: str, authorship_id: int
) -> dict | None:
    await cur.execute(
        """
        UPDATE source_authorships SET person_id = %s
        WHERE id = %s AND source = %s AND person_id IS NULL
        RETURNING excluded, author_name_normalized
        """,
        (person_id, authorship_id, source),
    )
    return await cur.fetchone()


async def batch_assign_orphans(cur: Any, person_id: int, sa_ids: list[int]) -> int:
    if not sa_ids:
        return 0

    # 1. Rattacher les source_authorships orphelines
    await cur.execute(
        """
        UPDATE source_authorships SET person_id = %s
        WHERE id = ANY(%s) AND person_id IS NULL
        RETURNING id
        """,
        (person_id, sa_ids),
    )
    assigned = cur.rowcount

    # 2. Créer les authorships vérité manquantes
    await cur.execute(
        """
        INSERT INTO authorships (publication_id, person_id,
            author_position, in_perimeter, is_corresponding, structure_ids)
        SELECT DISTINCT ON (sd.publication_id)
            sd.publication_id, %s,
            sa.author_position, sa.in_perimeter, sa.is_corresponding, sa.structure_ids
        FROM source_authorships sa
        JOIN source_publications sd ON sd.id = sa.source_publication_id
        WHERE sa.id = ANY(%s) AND sd.publication_id IS NOT NULL
        ORDER BY sd.publication_id,
            CASE sa.source WHEN 'hal' THEN 1 WHEN 'openalex' THEN 2 WHEN 'wos' THEN 3 END
        ON CONFLICT (publication_id, person_id) DO NOTHING
        """,
        (person_id, sa_ids),
    )

    # 3. Poser les FK authorship_id sur les source_authorships
    await cur.execute(
        """
        UPDATE source_authorships sa SET authorship_id = a.id
        FROM source_publications sd, authorships a
        WHERE sa.id = ANY(%s)
          AND sd.id = sa.source_publication_id
          AND a.publication_id = sd.publication_id
          AND a.person_id = %s
          AND sa.authorship_id IS NULL
        """,
        (sa_ids, person_id),
    )

    # 4. Récupérer les formes de nom observées et les ajouter
    await cur.execute(
        """
        SELECT DISTINCT author_name_normalized
        FROM source_authorships
        WHERE id = ANY(%s)
          AND author_name_normalized IS NOT NULL
          AND NOT excluded
        """,
        (sa_ids,),
    )
    rows = await cur.fetchall()
    forms = [r["author_name_normalized"] for r in rows]
    for form in forms:
        await _name_forms.add_name_form(cur, person_id, form)

    return assigned


async def ensure_truth_authorship(
    cur: Any, person_id: int, source: str, authorship_id: int
) -> None:
    # Trouver la publication_id via source_publications
    await cur.execute(
        """
        SELECT d.publication_id FROM source_authorships sa
        JOIN source_publications d ON d.id = sa.source_publication_id
        WHERE sa.id = %s AND sa.source = %s
        """,
        (authorship_id, source),
    )
    row = await cur.fetchone()
    pub_id = _val(row, 0) if row else None
    if not pub_id:
        return

    # 1. INSERT si pas déjà existant
    await cur.execute(
        """
        INSERT INTO authorships (publication_id, person_id)
        VALUES (%s, %s)
        ON CONFLICT (publication_id, person_id) DO NOTHING
        """,
        (pub_id, person_id),
    )

    # 2. FK sources (source_authorships.authorship_id → authorships.id)
    await cur.execute(
        """
        UPDATE source_authorships sa
        SET authorship_id = a.id
        FROM source_publications sd, authorships a
        WHERE sd.id = sa.source_publication_id
          AND a.publication_id = sd.publication_id
          AND a.person_id = sa.person_id
          AND sd.publication_id = %s
          AND sa.person_id = %s
          AND NOT sa.excluded
          AND sa.authorship_id IS NULL
        """,
        (pub_id, person_id),
    )

    # 3. author_position et is_corresponding
    await cur.execute(
        """
        UPDATE authorships a
        SET author_position = sub.pos,
            is_corresponding = COALESCE(a.is_corresponding, sub.corr)
        FROM (
            SELECT sa.authorship_id,
                   (array_agg(sa.author_position ORDER BY
                       CASE sa.source WHEN 'hal' THEN 1 WHEN 'openalex' THEN 2 WHEN 'wos' THEN 3 END
                   ))[1] AS pos,
                   (array_agg(sa.is_corresponding ORDER BY
                       CASE sa.source WHEN 'wos' THEN 1 WHEN 'openalex' THEN 2 WHEN 'hal' THEN 3 END
                   ))[1] AS corr
            FROM source_authorships sa
            WHERE sa.authorship_id IS NOT NULL AND NOT sa.excluded
            GROUP BY sa.authorship_id
        ) sub
        WHERE a.id = sub.authorship_id
          AND a.publication_id = %s AND a.person_id = %s
        """,
        (pub_id, person_id),
    )

    # 4. in_perimeter et structure_ids (union des sources)
    await cur.execute(
        f"""
        WITH src AS (
            SELECT sa.in_perimeter AS uca, sa.structure_ids AS sids
            FROM source_authorships sa
            JOIN source_publications sd ON sd.id = sa.source_publication_id
            WHERE sa.source IN {AUTHOR_SOURCES_SQL}
              AND sd.publication_id = %s AND sa.person_id = %s AND NOT sa.excluded
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
        WHERE a.publication_id = %s AND a.person_id = %s
        """,
        (pub_id, person_id, pub_id, person_id),
    )


async def count_authorships_with_name_form(
    cur: Any, person_id: int, name_form: str
) -> int:
    await cur.execute(
        f"""
        SELECT COUNT(*) AS n FROM source_authorships sa
        WHERE sa.person_id = %s AND sa.author_name_normalized = %s
          AND sa.source IN {AUTHOR_SOURCES_SQL}
        """,
        (person_id, name_form),
    )
    return _val(await cur.fetchone(), 0)
