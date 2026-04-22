"""SQL pour `person_name_forms`."""

from typing import Any

from domain.normalize import normalize_name


def refresh_name_forms(cur: Any, person_id: int, forms: set[str]) -> None:
    """Recalcule les formes de nom source 'persons' d'une personne.

    Supprime les anciennes formes 'persons' puis insère les nouvelles.
    Les formes partagées avec d'autres personnes ou d'autres sources
    sont préservées.

    `forms` : l'ensemble des formes normalisées calculées par le domaine
    (voir `compute_person_name_forms`).
    """
    # 1a. Formes dont 'persons' est la seule source : retirer le person_id
    cur.execute(
        """
        UPDATE person_name_forms
        SET person_ids = array_remove(person_ids, %s)
        WHERE %s = ANY(person_ids)
          AND sources = ARRAY['persons']
        """,
        (person_id, person_id),
    )
    # 1b. Formes multi-sources : retirer 'persons' de sources, garder person_id
    cur.execute(
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
    cur.execute("""
        DELETE FROM person_name_forms
        WHERE person_ids = '{}' OR person_ids IS NULL
    """)
    # 2. Ajouter les nouvelles formes
    for form in forms:
        add_name_form(cur, person_id, form, source="persons")


def add_name_form(cur: Any, person_id: int, full_name: str, source: str | None = None) -> None:
    """Ajoute une forme de nom à person_name_forms si elle n'existe pas déjà.

    Si `source` est fourni (ex: 'hal', 'openalex', 'persons'), il est ajouté
    au tableau sources de la forme de nom.
    """
    if not full_name or not full_name.strip():
        return
    norm = normalize_name(full_name)
    if not norm:
        return
    if source:
        cur.execute(
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
        cur.execute(
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


def detach_name_form(cur: Any, person_id: int, name_form: str) -> None:
    """Détache une personne d'une forme de nom. Supprime la forme si elle
    devient orpheline."""
    cur.execute(
        """
        UPDATE person_name_forms
        SET person_ids = array_remove(person_ids, %s)
        WHERE name_form = %s
        """,
        (person_id, name_form),
    )
    cur.execute(
        """
        DELETE FROM person_name_forms
        WHERE name_form = %s AND person_ids = '{}'
        """,
        (name_form,),
    )
