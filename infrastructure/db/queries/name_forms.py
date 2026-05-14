"""Query service : SQL du peuplement de `person_name_forms`.

Appelé par `application/pipeline/persons/populate_person_name_forms.py`.
Collecte les formes brutes (table `persons` + `source_authorships`),
passe par une table temporaire pour normalisation SQL via
`normalize_name_form()`, puis synchronise `person_name_forms`.

La colonne de vérité est `persons jsonb` au format
``{ "<person_id>": ["<source1>", ...], ... }`` — voir
`domain/persons/name_forms.py`. Les anciennes colonnes `person_ids` /
`sources` ne sont plus écrites depuis ce module (chantier
`DATA_person-name-forms-normalisation`, Phase 4) ; elles seront DROP en
Phase 6.
"""

from typing import Any

from sqlalchemy import Connection, bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.ports.pipeline.name_forms import NameFormsQueries
from domain.persons.name_forms import PersonsDict


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
    """Normalise les formes brutes via `normalize_name_form()` SQL.

    Retourne les triplets ``(name_form, person_id, source)`` distincts.
    L'agrégation par forme est faite côté Python par l'orchestrateur via
    les helpers `domain/persons/name_forms.py` (cf. note du chantier :
    fusion en Python plutôt qu'en SQL, l'orchestrateur a déjà la donnée
    en mémoire).
    """
    rows = conn.execute(
        text("""
            SELECT DISTINCT normalize_name_form(raw_text) AS name_form,
                   person_id, source
            FROM _raw_forms
            WHERE trim(raw_text) != ''
        """)
    ).all()
    return [dict(r._mapping) for r in rows]


def drop_temp_raw_forms_table(conn: Connection) -> None:
    conn.execute(text("DROP TABLE _raw_forms"))


def fetch_existing_name_forms(conn: Connection) -> list[dict[str, Any]]:
    """Charge toutes les lignes de `person_name_forms` (id, name_form, persons)."""
    rows = conn.execute(text("SELECT id, name_form, persons FROM person_name_forms")).all()
    return [dict(r._mapping) for r in rows]


def update_name_form(conn: Connection, form_id: int, persons: PersonsDict) -> None:
    """Met à jour le `persons` d'une ligne existante de `person_name_forms`.

    Le dict `persons` doit déjà être consolidé côté Python (fusion par
    clé, sources triées) — cette fonction n'opère aucun merge SQL.
    """
    stmt = text("""
        UPDATE person_name_forms
        SET persons = :persons, updated_at = now()
        WHERE id = :form_id
    """).bindparams(bindparam("persons", type_=JSONB))
    conn.execute(stmt, {"persons": persons, "form_id": form_id})


def insert_name_form(conn: Connection, name_form: str, persons: PersonsDict) -> None:
    """INSERT d'une nouvelle ligne `person_name_forms`.

    L'orchestrateur calcule le diff (`expected_forms` vs `existing`) et
    n'appelle ce point que pour les formes absentes en base. Pas de
    ON CONFLICT côté SQL : la fusion par forme est déjà faite en
    Python.
    """
    stmt = text("""
        INSERT INTO person_name_forms (name_form, persons)
        VALUES (:name_form, :persons)
    """).bindparams(bindparam("persons", type_=JSONB))
    conn.execute(stmt, {"name_form": name_form, "persons": persons})


def delete_name_form(conn: Connection, form_id: int) -> None:
    """Supprime une ligne de `person_name_forms` par id."""
    conn.execute(
        text("DELETE FROM person_name_forms WHERE id = :form_id"),
        {"form_id": form_id},
    )


class PgNameFormsQueries(NameFormsQueries):
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

    def update_name_form(self, conn: Connection, form_id: int, persons: PersonsDict) -> None:
        update_name_form(conn, form_id, persons)

    def insert_name_form(self, conn: Connection, name_form: str, persons: PersonsDict) -> None:
        insert_name_form(conn, name_form, persons)

    def delete_name_form(self, conn: Connection, form_id: int) -> None:
        delete_name_form(conn, form_id)
