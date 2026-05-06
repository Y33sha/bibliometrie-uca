"""SQL async pour `person_name_forms`.

Mode dispatch : chaque fonction accepte un curseur psycopg ou une
AsyncConnection SA. Phase 4 supprimera la branche psycopg.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from domain.normalize import normalize_name


async def refresh_name_forms(conn: Any, person_id: int, forms: set[str]) -> None:
    if isinstance(conn, AsyncConnection):
        await conn.execute(
            text("""
                UPDATE person_name_forms
                SET person_ids = array_remove(person_ids, :pid)
                WHERE :pid = ANY(person_ids)
                  AND sources = ARRAY['persons']
            """),
            {"pid": person_id},
        )
        await conn.execute(
            text("""
                UPDATE person_name_forms
                SET sources = array_remove(sources, 'persons'),
                    updated_at = now()
                WHERE :pid = ANY(person_ids)
                  AND 'persons' = ANY(sources)
                  AND array_length(sources, 1) > 1
            """),
            {"pid": person_id},
        )
        await conn.execute(
            text("DELETE FROM person_name_forms WHERE person_ids = '{}' OR person_ids IS NULL")
        )
        for form in forms:
            await add_name_form(conn, person_id, form, source="persons")
        return

    # 1a. Formes dont 'persons' est la seule source : retirer le person_id
    await conn.execute(
        """
        UPDATE person_name_forms
        SET person_ids = array_remove(person_ids, %s)
        WHERE %s = ANY(person_ids)
          AND sources = ARRAY['persons']
        """,
        (person_id, person_id),
    )
    # 1b. Formes multi-sources : retirer 'persons' de sources, garder person_id
    await conn.execute(
        """
        UPDATE person_name_forms
        SET sources = array_remove(sources, 'persons'),
            updated_at = now()
        WHERE %s = ANY(person_ids)
          AND 'persons' = ANY(sources)
          AND array_length(sources, 1) > 1
        """,
        (person_id,),
    )
    # 1c. Nettoyer les formes devenues vides
    await conn.execute("""
        DELETE FROM person_name_forms
        WHERE person_ids = '{}' OR person_ids IS NULL
    """)
    # 2. Ajouter les nouvelles formes
    for form in forms:
        await add_name_form(conn, person_id, form, source="persons")


async def add_name_form(
    conn: Any, person_id: int, full_name: str, source: str | None = None
) -> None:
    if not full_name or not full_name.strip():
        return
    norm = normalize_name(full_name)
    if not norm:
        return
    if isinstance(conn, AsyncConnection):
        if source:
            await conn.execute(
                text("""
                    INSERT INTO person_name_forms (name_form, person_ids, sources)
                    VALUES (:nf, ARRAY[:pid], ARRAY[:src])
                    ON CONFLICT (name_form) DO UPDATE
                    SET person_ids = (
                            SELECT array_agg(DISTINCT x)
                            FROM unnest(person_name_forms.person_ids || ARRAY[:pid]) AS x
                        ),
                        sources = (
                            SELECT array_agg(DISTINCT x ORDER BY x)
                            FROM unnest(
                                COALESCE(person_name_forms.sources, '{}') || ARRAY[:src]
                            ) AS x
                        ),
                        updated_at = now()
                """),
                {"nf": norm, "pid": person_id, "src": source},
            )
        else:
            await conn.execute(
                text("""
                    INSERT INTO person_name_forms (name_form, person_ids)
                    VALUES (:nf, ARRAY[:pid])
                    ON CONFLICT (name_form) DO UPDATE
                    SET person_ids = (
                        SELECT array_agg(DISTINCT x)
                        FROM unnest(
                            person_name_forms.person_ids || ARRAY[:pid]
                        ) AS x
                    )
                """),
                {"nf": norm, "pid": person_id},
            )
        return
    if source:
        await conn.execute(
            """
            INSERT INTO person_name_forms (name_form, person_ids, sources)
            VALUES (%s, ARRAY[%s], ARRAY[%s])
            ON CONFLICT (name_form) DO UPDATE
            SET person_ids = (
                    SELECT array_agg(DISTINCT x)
                    FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
                ),
                sources = (
                    SELECT array_agg(DISTINCT x ORDER BY x)
                    FROM unnest(COALESCE(person_name_forms.sources, '{}') || ARRAY[%s]) AS x
                ),
                updated_at = now()
            """,
            (norm, person_id, source, person_id, source),
        )
    else:
        await conn.execute(
            """
            INSERT INTO person_name_forms (name_form, person_ids)
            VALUES (%s, ARRAY[%s])
            ON CONFLICT (name_form) DO UPDATE
            SET person_ids = (
                SELECT array_agg(DISTINCT x)
                FROM unnest(person_name_forms.person_ids || ARRAY[%s]) AS x
            )
            """,
            (norm, person_id, person_id),
        )


async def detach_name_form(conn: Any, person_id: int, name_form: str) -> None:
    if isinstance(conn, AsyncConnection):
        await conn.execute(
            text(
                "UPDATE person_name_forms SET person_ids = array_remove(person_ids, :pid) "
                "WHERE name_form = :nf"
            ),
            {"pid": person_id, "nf": name_form},
        )
        await conn.execute(
            text("DELETE FROM person_name_forms WHERE name_form = :nf AND person_ids = '{}'"),
            {"nf": name_form},
        )
        return
    await conn.execute(
        """
        UPDATE person_name_forms
        SET person_ids = array_remove(person_ids, %s)
        WHERE name_form = %s
        """,
        (person_id, name_form),
    )
    await conn.execute(
        """
        DELETE FROM person_name_forms
        WHERE name_form = %s AND person_ids = '{}'
        """,
        (name_form,),
    )
