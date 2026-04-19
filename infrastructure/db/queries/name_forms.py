"""Query service : SQL du peuplement de `person_name_forms`.

Appelé par `application/pipeline/build/populate_person_name_forms.py`.
Collecte les formes brutes (table `persons` + `source_authorships`),
passe par une table temporaire pour normalisation SQL via
`normalize_name_form()`, puis synchronise `person_name_forms`.
"""

from typing import Any

from infrastructure.db_helpers import rows_as_dicts


def fetch_active_persons_names(cur: Any) -> list[dict[str, Any]]:
    """`(id, first_name, last_name)` des personnes actives avec un nom."""
    cur.execute("""
        SELECT id,
               trim(first_name) AS first_name,
               trim(last_name) AS last_name
        FROM persons
        WHERE last_name IS NOT NULL AND last_name != ''
          AND rejected = FALSE
    """)
    return rows_as_dicts(cur)


def fetch_source_authorship_name_forms(cur: Any) -> list[dict[str, Any]]:
    """`(name_form, person_id, source)` distincts des authorships non exclus."""
    cur.execute("""
        SELECT DISTINCT sa.author_name_normalized AS name_form, sa.person_id, sa.source
        FROM source_authorships sa
        WHERE sa.person_id IS NOT NULL AND NOT sa.excluded
          AND sa.author_name_normalized IS NOT NULL AND sa.author_name_normalized != ''
    """)
    return rows_as_dicts(cur)


def create_temp_raw_forms_table(cur: Any) -> None:
    """Crée la table temporaire `_raw_forms(raw_text, person_id, source)`."""
    cur.execute("CREATE TEMP TABLE _raw_forms (raw_text TEXT, person_id INT, source TEXT)")


def insert_raw_forms_batch(cur: Any, rows: list[tuple[str, int, str]]) -> None:
    """Insert par batch dans la table temporaire `_raw_forms`."""
    cur.executemany("INSERT INTO _raw_forms VALUES (%s, %s, %s)", rows)


def fetch_normalized_forms_from_temp(cur: Any) -> list[dict[str, Any]]:
    """Normalise les formes brutes via `normalize_name_form()` SQL et agrège."""
    cur.execute("""
        SELECT normalize_name_form(raw_text) AS name_form,
               array_agg(DISTINCT person_id ORDER BY person_id) AS person_ids,
               array_agg(DISTINCT source ORDER BY source) AS sources
        FROM _raw_forms
        WHERE trim(raw_text) != ''
        GROUP BY normalize_name_form(raw_text)
    """)
    return rows_as_dicts(cur)


def drop_temp_raw_forms_table(cur: Any) -> None:
    cur.execute("DROP TABLE _raw_forms")


def fetch_existing_name_forms(cur: Any) -> list[dict[str, Any]]:
    """Charge toutes les lignes de `person_name_forms`."""
    cur.execute("SELECT id, name_form, person_ids, sources FROM person_name_forms")
    return rows_as_dicts(cur)


def update_name_form(cur: Any, form_id: int, person_ids: list[int], sources: list[str]) -> None:
    """Met à jour une ligne existante de `person_name_forms`."""
    cur.execute(
        """
        UPDATE person_name_forms
        SET person_ids = %s, sources = %s, updated_at = now()
        WHERE id = %s
        """,
        (person_ids, sources, form_id),
    )


def insert_name_form_with_merge(
    cur: Any, name_form: str, person_ids: list[int], sources: list[str]
) -> None:
    """INSERT avec fusion `ON CONFLICT` (union `person_ids` et `sources`)."""
    cur.execute(
        """
        INSERT INTO person_name_forms (name_form, person_ids, sources)
        VALUES (%s, %s, %s)
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
        """,
        (name_form, person_ids, sources),
    )


def delete_name_form(cur: Any, form_id: int) -> None:
    """Supprime une ligne de `person_name_forms` par id."""
    cur.execute("DELETE FROM person_name_forms WHERE id = %s", (form_id,))
