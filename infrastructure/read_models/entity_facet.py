"""Facette d'entité à forte cardinalité (éditeur, revue, auteur), commune à la liste des publications et au tableau de bord.

Rend les entités les plus représentées parmi les publications qui satisfont une clause fournie par l'appelant, avec leur décompte. Une recherche par nom borne la requête.
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
    # Jointure depuis `publications p` : une ligne par couple publication–entité.
    join: str


# La revue sort de `publications.journal_id`, l'éditeur de la revue. L'auteur passe par `authorships`, unique par couple publication–personne ; une personne rejetée n'est pas proposée.
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
}


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

    La jointure de l'entité rend une ligne par couple publication–entité. `COUNT(*)` par entité égale donc le nombre de publications distinctes, pourvu que `where_sql` se compose de filtres scalaires ou en `EXISTS`. Un terme de recherche d'au moins deux caractères filtre les entités par nom.
    """
    sql = ENTITY_SQL[kind]
    params = dict(binds)
    name_filter = ""
    if len(search.strip()) >= 2:
        name_filter = f" AND unaccent({sql.label}) ILIKE unaccent(:q)"
        params["q"] = f"%{search.strip()}%"
    params["lim"] = limit
    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(
        text(f"""
            SELECT {sql.id} AS id, {sql.label} AS label, COUNT(*) AS n
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
