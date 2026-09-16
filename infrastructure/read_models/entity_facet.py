"""Facette d'entité à forte cardinalité (éditeur, revue, auteur, sujet).

`entity_facet_rows` rend les entités les plus représentées parmi les publications qui satisfont une clause fournie par l'appelant, avec leur décompte : la liste des publications et le tableau de bord s'en servent. `entity_name_clause` borne les options au terme cherché, quelle que soit la population décomptée.
"""

from collections.abc import Mapping
from typing import NamedTuple

from sqlalchemy import Connection, text

from application.ports.read_models._common import EntityFacetItem, EntityKind


class EntitySql(NamedTuple):
    """Fragments SQL d'un type d'entité (valeurs figées, aucune injection)."""

    # Table de l'entité avec son alias, pour lire un libellé par identifiant.
    table: str
    id: str
    label: str
    # Jointure depuis `publications p` vers l'entité.
    join: str


# La revue sort de `publications.journal_id`, l'éditeur de la revue. L'auteur passe par `authorships` ; une personne rejetée n'est pas proposée. Le sujet passe par `publication_subjects`, qui porte une ligne par source pour un même couple publication–sujet.
ENTITY_SQL: dict[EntityKind, EntitySql] = {
    "journal": EntitySql(
        table="journals j",
        id="j.id",
        label="j.title",
        join="JOIN journals j ON j.id = p.journal_id",
    ),
    "publisher": EntitySql(
        table="publishers pub",
        id="pub.id",
        label="pub.name",
        join="JOIN journals j ON j.id = p.journal_id JOIN publishers pub ON pub.id = j.publisher_id",
    ),
    "person": EntitySql(
        table="persons pe",
        id="pe.id",
        label="pe.first_name || ' ' || pe.last_name",
        join=(
            "JOIN authorships au ON au.publication_id = p.id AND au.roles && ARRAY['author']::text[] "
            "JOIN persons pe ON pe.id = au.person_id AND pe.rejected IS NOT TRUE"
        ),
    ),
    "subject": EntitySql(
        table="subjects s",
        id="s.id",
        label="s.label",
        join=(
            "JOIN publication_subjects ps ON ps.publication_id = p.id "
            "JOIN subjects s ON s.id = ps.subject_id"
        ),
    ),
}


def entity_name_clause(label_sql: str, search: str) -> tuple[str, dict[str, object]]:
    """Condition qui restreint une facette d'entité aux noms portant le terme cherché, à ajouter au WHERE.

    Le fragment rendu est vide en deçà de deux caractères : le terme ne discrimine alors rien.
    """
    term = search.strip()
    if len(term) < 2:
        return "", {}
    return f" AND unaccent({label_sql}) ILIKE unaccent(:q)", {"q": f"%{term}%"}


def entity_facet_rows(
    conn: Connection,
    *,
    kind: EntityKind,
    where_sql: str,
    binds: Mapping[str, object],
    search: str,
    limit: int,
) -> list[EntityFacetItem]:
    """Entités `kind` les plus représentées parmi les publications `p` qui satisfont `where_sql`.

    Le décompte porte sur les publications distinctes : la jointure d'un sujet rend une ligne par source. Un terme de recherche d'au moins deux caractères filtre les entités par nom.
    """
    sql = ENTITY_SQL[kind]
    name_filter, name_binds = entity_name_clause(sql.label, search)
    params: dict[str, object] = {**binds, **name_binds, "lim": limit}
    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(
        text(f"""
            SELECT {sql.id} AS id, {sql.label} AS label, COUNT(DISTINCT p.id) AS n
            FROM publications p
            {sql.join}
            WHERE {where_sql}{name_filter}
            GROUP BY {sql.id}, {sql.label}
            ORDER BY n DESC, label
            LIMIT :lim
        """),
        params,
    ).all()
    return [EntityFacetItem(id=r.id, label=r.label, count=r.n) for r in rows]
