"""SQL pour `person_name_forms`.

Table dénormalisée `(name_form, person_id, sources text[])` avec PK composite `(name_form, person_id)`. Toutes les opérations s'expriment en INSERT/UPDATE/DELETE directs sur la table.
"""

from typing import cast

from sqlalchemy import Connection, text

from application.ports.repositories.person_repository import NameFormStatusRow
from domain.errors import NotFoundError
from domain.normalize import normalize_name
from domain.sources.registry import AUTHOR_SOURCES
from infrastructure.db.sql_fragments import in_clause


def refresh_name_forms(conn: Connection, person_id: int, forms: set[str]) -> None:
    """Retire `'persons'` des sources de toutes les rows de la personne, supprime celles dont la liste de sources devient vide, puis pose les formes calculées (source `'persons'`) via un UPSERT qui fusionne avec les sources existantes."""
    conn.execute(
        text("""
            UPDATE person_name_forms
            SET sources = array_remove(sources, 'persons')
            WHERE person_id = :pid AND 'persons' = ANY(sources)
        """),
        {"pid": person_id},
    )
    conn.execute(
        text("DELETE FROM person_name_forms WHERE person_id = :pid AND sources = '{}'"),
        {"pid": person_id},
    )
    for form in forms:
        add_person_source(conn, name_form=form, person_id=person_id, source="persons")


def add_name_form(
    conn: Connection, person_id: int, full_name: str, source: str | None = None
) -> None:
    """Pose le couple `(name_form, person_id)` avec `sources = [source]` (vide si `source` est None) ; sur conflit, fusionne avec les sources existantes."""
    if not full_name or not full_name.strip():
        return
    norm = normalize_name(full_name)
    if not norm:
        return
    add_person_source(conn, name_form=norm, person_id=person_id, source=source)


def update_name_form_status(
    conn: Connection, person_id: int, name_form: str, status: str
) -> NameFormStatusRow:
    row = conn.execute(
        text(
            "UPDATE person_name_forms SET status = CAST(:st AS identifier_status) "
            "WHERE name_form = :nf AND person_id = :pid "
            "RETURNING person_id, name_form, CAST(status AS text) AS status"
        ),
        {"st": status, "nf": name_form, "pid": person_id},
    ).first()
    if not row:
        raise NotFoundError(f"Forme de nom {name_form!r} introuvable pour la personne {person_id}")
    return cast(NameFormStatusRow, dict(row._mapping))


def delete_orphan_name_forms_for_person(conn: Connection, person_id: int) -> int:
    result = conn.execute(
        text(f"""
            DELETE FROM person_name_forms pnf
            WHERE pnf.person_id = :pid
              AND pnf.status = 'pending'
              AND NOT ('persons' = ANY(pnf.sources))
              AND NOT EXISTS (
                  SELECT 1 FROM source_authorships sa
                  JOIN author_identifying_keys aik ON aik.id = sa.identity_id
                  WHERE sa.person_id = :pid
                    AND aik.author_name_normalized = pnf.name_form
                    AND sa.source IN {in_clause(AUTHOR_SOURCES)}
              )
        """),
        {"pid": person_id},
    )
    return result.rowcount


def add_person_source(
    conn: Connection, *, name_form: str, person_id: int, source: str | None
) -> None:
    """Ajoute une source au couple `(name_form, person_id)`, idempotent.

    Crée la row si elle est absente (avec `sources = [source]` ou `sources = []` si `source is None`). Sur conflit, fusionne la source dans le tableau existant — déduplication + tri stable via `array_agg(DISTINCT ... ORDER BY ...)`.

    Statut : toute forme entre en `pending` ; seule une action admin la confirme ou la rejette. L'appartenance d'une forme au nom canonique (source `'persons'`) se lit dans `sources`, non dans le statut. Une fusion préserve le verdict existant.
    """
    new_sources = [source] if source else []
    conn.execute(
        text("""
            INSERT INTO person_name_forms (name_form, person_id, sources, status)
            VALUES (:nf, :pid, :new_sources, 'pending'::identifier_status)
            ON CONFLICT (name_form, person_id) DO UPDATE SET
                sources = (
                    SELECT COALESCE(array_agg(DISTINCT s ORDER BY s), '{}'::text[])
                    FROM unnest(person_name_forms.sources || EXCLUDED.sources) AS s
                )
        """),
        {"nf": name_form, "pid": person_id, "new_sources": new_sources},
    )
