"""Query service : SQL du peuplement de `person_name_forms`.

Appelé par `application/pipeline/build/populate_person_name_forms.py`.
Collecte les formes brutes (table `persons` + `source_authorships`),
passe par une table temporaire pour normalisation SQL via
`normalize_name_form()`, puis synchronise `person_name_forms`.
"""

from typing import Any

from sqlalchemy import Connection, text


def fetch_persons_names(conn: Connection) -> list[dict[str, Any]]:
    """`(id, first_name, last_name)` de toutes les personnes avec un nom.

    Inclut les ``rejected = TRUE`` : leurs name_forms doivent rester
    présentes dans ``person_name_forms`` pour servir d'ancre au matching
    et empêcher la re-création en boucle des entités douteuses
    (artefacts de parsing source, noms d'organisations, etc.) à chaque
    run pipeline.
    """
    rows = conn.execute(
        text("""
            SELECT id,
                   trim(first_name) AS first_name,
                   trim(last_name) AS last_name
            FROM persons
            WHERE last_name IS NOT NULL AND last_name != ''
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def fetch_source_authorship_name_forms(conn: Connection) -> list[dict[str, Any]]:
    """`(name_form, person_id, source)` distincts des authorships non exclus."""
    rows = conn.execute(
        text("""
            SELECT DISTINCT sa.author_name_normalized AS name_form,
                   sa.person_id, sa.source::text AS source
            FROM source_authorships sa
            WHERE sa.person_id IS NOT NULL AND NOT sa.excluded
              AND sa.author_name_normalized IS NOT NULL AND sa.author_name_normalized != ''
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def create_temp_raw_forms_table(conn: Connection) -> None:
    """Crée la table temporaire `_raw_forms(raw_text, person_id, source)`."""
    conn.execute(text("CREATE TEMP TABLE _raw_forms (raw_text TEXT, person_id INT, source TEXT)"))


def insert_raw_forms_batch(conn: Connection, rows: list[dict[str, Any]]) -> None:
    """Insert par batch dans la table temporaire `_raw_forms`.

    Chaque dict du batch a les clés ``raw_text``, ``person_id``, ``source``.
    """
    if not rows:
        return
    conn.execute(
        text("INSERT INTO _raw_forms VALUES (:raw_text, :person_id, :source)"),
        rows,
    )


def fetch_normalized_forms_from_temp(conn: Connection) -> list[dict[str, Any]]:
    """Normalise les formes brutes via `normalize_name_form()` SQL et agrège."""
    rows = conn.execute(
        text("""
            SELECT normalize_name_form(raw_text) AS name_form,
                   array_agg(DISTINCT person_id ORDER BY person_id) AS person_ids,
                   array_agg(DISTINCT source ORDER BY source) AS sources
            FROM _raw_forms
            WHERE trim(raw_text) != ''
            GROUP BY normalize_name_form(raw_text)
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def drop_temp_raw_forms_table(conn: Connection) -> None:
    conn.execute(text("DROP TABLE _raw_forms"))


def fetch_existing_name_forms(conn: Connection) -> list[dict[str, Any]]:
    """Charge toutes les lignes de `person_name_forms`."""
    rows = conn.execute(
        text("SELECT id, name_form, person_ids, sources FROM person_name_forms")
    ).all()
    return [dict(r._mapping) for r in rows]


def update_name_form(
    conn: Connection, form_id: int, person_ids: list[int], sources: list[str]
) -> None:
    """Met à jour une ligne existante de `person_name_forms`."""
    conn.execute(
        text("""
            UPDATE person_name_forms
            SET person_ids = :person_ids, sources = :sources, updated_at = now()
            WHERE id = :form_id
        """),
        {"person_ids": person_ids, "sources": sources, "form_id": form_id},
    )


def insert_name_form_with_merge(
    conn: Connection, name_form: str, person_ids: list[int], sources: list[str]
) -> None:
    """INSERT avec fusion `ON CONFLICT` (union `person_ids` et `sources`)."""
    conn.execute(
        text("""
            INSERT INTO person_name_forms (name_form, person_ids, sources)
            VALUES (:name_form, :person_ids, :sources)
            ON CONFLICT (name_form) DO UPDATE SET
                person_ids = (
                    SELECT array_agg(DISTINCT x ORDER BY x)
                    FROM unnest(person_name_forms.person_ids || EXCLUDED.person_ids) AS x
                ),
                sources = (
                    SELECT array_agg(DISTINCT x ORDER BY x)
                    FROM unnest(COALESCE(person_name_forms.sources, '{}') || EXCLUDED.sources) AS x
                ),
                updated_at = now()
        """),
        {"name_form": name_form, "person_ids": person_ids, "sources": sources},
    )


def delete_name_form(conn: Connection, form_id: int) -> None:
    """Supprime une ligne de `person_name_forms` par id."""
    conn.execute(
        text("DELETE FROM person_name_forms WHERE id = :form_id"),
        {"form_id": form_id},
    )


class PgNameFormsQueries:
    """Adapter PostgreSQL pour `application.ports.name_forms.NameFormsQueries`."""

    def fetch_persons_names(self, conn: Connection) -> list[dict[str, Any]]:
        return fetch_persons_names(conn)

    def fetch_source_authorship_name_forms(self, conn: Connection) -> list[dict[str, Any]]:
        return fetch_source_authorship_name_forms(conn)

    def create_temp_raw_forms_table(self, conn: Connection) -> None:
        create_temp_raw_forms_table(conn)

    def insert_raw_forms_batch(self, conn: Connection, rows: list[dict[str, Any]]) -> None:
        insert_raw_forms_batch(conn, rows)

    def fetch_normalized_forms_from_temp(self, conn: Connection) -> list[dict[str, Any]]:
        return fetch_normalized_forms_from_temp(conn)

    def drop_temp_raw_forms_table(self, conn: Connection) -> None:
        drop_temp_raw_forms_table(conn)

    def fetch_existing_name_forms(self, conn: Connection) -> list[dict[str, Any]]:
        return fetch_existing_name_forms(conn)

    def update_name_form(
        self, conn: Connection, form_id: int, person_ids: list[int], sources: list[str]
    ) -> None:
        update_name_form(conn, form_id, person_ids, sources)

    def insert_name_form_with_merge(
        self, conn: Connection, name_form: str, person_ids: list[int], sources: list[str]
    ) -> None:
        insert_name_form_with_merge(conn, name_form, person_ids, sources)

    def delete_name_form(self, conn: Connection, form_id: int) -> None:
        delete_name_form(conn, form_id)
