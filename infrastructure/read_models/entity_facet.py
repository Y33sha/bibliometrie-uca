"""Facette d'entité à forte cardinalité (éditeur, revue), commune à la liste des publications et au tableau de bord.

Rend les entités les plus représentées parmi les publications qui satisfont une clause fournie par l'appelant, avec leur décompte. Une recherche par nom borne la requête.
"""

from collections.abc import Mapping

from sqlalchemy import Connection, text

from application.ports.read_models._common import EntityFacetItem, EntityKind

# Liaison SQL par entité : identifiant, libellé, jointure additionnelle. La revue sort de `publications.journal_id` ; l'éditeur passe par une jointure un-à-un vers `publishers` (qui exclut les publications sans éditeur).
_ENTITY_SQL: dict[EntityKind, dict[str, str]] = {
    "journal": {"id": "j.id", "label": "j.title", "join": ""},
    "publisher": {
        "id": "pub.id",
        "label": "pub.name",
        "join": "JOIN publishers pub ON pub.id = j.publisher_id",
    },
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

    `where_sql` se compose de filtres scalaires ou en `EXISTS` : sans jointure démultipliante, `COUNT(*)` par entité égale le nombre de publications distinctes. Un terme de recherche d'au moins deux caractères filtre les entités par nom.
    """
    sql = _ENTITY_SQL[kind]
    params = dict(binds)
    name_filter = ""
    if len(search.strip()) >= 2:
        name_filter = f" AND unaccent({sql['label']}) ILIKE unaccent(:q)"
        params["q"] = f"%{search.strip()}%"
    params["lim"] = limit
    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(
        text(f"""
            SELECT {sql["id"]} AS id, {sql["label"]} AS label, COUNT(*) AS n
            FROM publications p
            LEFT JOIN journals j ON j.id = p.journal_id {sql["join"]}
            WHERE {where_sql} AND {sql["id"]} IS NOT NULL{name_filter}
            GROUP BY {sql["id"]}, {sql["label"]}
            ORDER BY n DESC, label
            LIMIT :lim
        """),
        params,
    ).all()
    return [EntityFacetItem(id=r.id, label=r.label, count=r.n) for r in rows]
