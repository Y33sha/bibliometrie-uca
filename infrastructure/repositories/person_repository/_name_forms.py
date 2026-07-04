"""SQL pour `person_name_forms`.

Table dénormalisée `(name_form, person_id, sources text[])` avec PK
composite `(name_form, person_id)`. Toutes les opérations s'expriment
en INSERT/UPDATE/DELETE directs : pas de JSONB à manipuler en mémoire,
pas de représentation in-memory du mapping. Les noms historiques
``add_person_source`` / ``remove_person_source`` / ``is_ambiguous``
sont conservés ici comme opérations SQL (ils manipulaient le JSONB
auparavant — leur sémantique métier survit, leur implémentation est
DB).
"""

from typing import cast

from sqlalchemy import Connection, text

from application.ports.repositories.person_repository import NameFormStatusRow
from domain.errors import NotFoundError
from domain.normalize import normalize_name
from domain.sources.registry import AUTHOR_SOURCES_SQL


def refresh_name_forms(conn: Connection, person_id: int, forms: set[str]) -> None:
    """Recalcule les formes de nom source ``'persons'`` d'une personne.

    Retire ``'persons'`` des sources de toutes les rows de cette
    personne, supprime les rows devenues sans source, puis pose les
    nouvelles formes (avec source ``'persons'``) via un UPSERT qui
    fusionne avec les sources existantes (cross-source).

    `forms` : l'ensemble des formes normalisées calculées par le
    domaine (voir `compute_person_name_forms`).
    """
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
    """Ajoute une forme de nom (normalisée) à une personne, idempotent.

    Normalise `full_name`, puis pose le couple ``(name_form,
    person_id)`` avec ``sources = [source]`` (vide si `source` est None).
    Sur conflit, fusionne avec les sources existantes.
    """
    if not full_name or not full_name.strip():
        return
    norm = normalize_name(full_name)
    if not norm:
        return
    add_person_source(conn, name_form=norm, person_id=person_id, source=source)


def update_name_form_status(
    conn: Connection, person_id: int, name_form: str, status: str
) -> NameFormStatusRow:
    """Change le statut d'une forme de nom. Retourne {person_id, name_form, status}.

    `rejected` bloque durablement le retour de la forme au matching par nom (le
    recompute préserve le verdict, `fetch_name_form_map` l'exclut) ; `confirmed`
    corrobore les matchs par identifiant sans test de nom. Lève `NotFoundError` si
    le couple `(name_form, person_id)` n'existe pas.
    """
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
    """Supprime les formes de nom d'une personne qui proviennent des sources
    mais ne sont plus portées par aucune `source_authorship` active.

    Appelé après un rejet de contribution : détacher les sources d'une paire
    peut laisser une forme de nom que plus aucune source n'atteste. Les formes
    calculées à partir du nom de la personne (source ``'persons'``) sont
    conservées : elles ne dépendent pas des sources.

    Ne touche que les formes ``pending`` : un verdict ``confirmed``/``rejected`` est
    préservé même devenu orphelin — supprimer une forme ``rejected`` détruirait le
    blocage de non-retour qu'elle matérialise.

    Retourne le nombre de formes supprimées."""
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
                    AND sa.source IN {AUTHOR_SOURCES_SQL}
              )
        """),
        {"pid": person_id},
    )
    return result.rowcount


def add_person_source(
    conn: Connection, *, name_form: str, person_id: int, source: str | None
) -> None:
    """Ajoute une source au couple ``(name_form, person_id)``, idempotent.

    Crée la row si elle n'existe pas (avec `sources = [source]` ou
    `sources = []` si `source is None`). Sur conflit, fusionne la
    source dans le tableau existant — déduplication + tri stable
    via ``array_agg(DISTINCT ... ORDER BY ...)``.

    Statut : toute forme entre en ``pending`` ; seule une action admin la confirme ou
    la rejette. L'appartenance d'une forme au nom canonique (source ``'persons'``) se
    lit dans ``sources``, pas dans le statut. Une fusion préserve le verdict existant.
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


def remove_person_source(conn: Connection, *, name_form: str, person_id: int, source: str) -> None:
    """Retire une source du couple ``(name_form, person_id)``.

    Si la liste devient vide, supprime la row (le couple disparaît).
    No-op si la row n'existe pas ou si la source n'y figure pas.
    """
    conn.execute(
        text("""
            UPDATE person_name_forms
            SET sources = array_remove(sources, :source)
            WHERE name_form = :nf AND person_id = :pid AND :source = ANY(sources)
        """),
        {"nf": name_form, "pid": person_id, "source": source},
    )
    conn.execute(
        text("""
            DELETE FROM person_name_forms
            WHERE name_form = :nf AND person_id = :pid AND sources = '{}'
        """),
        {"nf": name_form, "pid": person_id},
    )


def is_ambiguous(conn: Connection, name_form: str) -> bool:
    """True si la forme est associée à plus d'une personne."""
    row = conn.execute(
        text("SELECT COUNT(*) AS n FROM person_name_forms WHERE name_form = :nf"),
        {"nf": name_form},
    ).one()
    return int(row.n) > 1
