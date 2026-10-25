"""Facette d'entité à forte cardinalité (éditeur, revue, auteur, sujet).

`entity_facet_rows` rend les entités les plus représentées parmi les publications qui satisfont une clause fournie par l'appelant, avec leur décompte : la liste des publications et le tableau de bord s'en servent. `entity_name_clause` borne les options au terme cherché, quelle que soit la population décomptée.
"""

from collections.abc import Mapping
from typing import NamedTuple

from sqlalchemy import Connection, text

from application.ports.read_models._common import EntityFacetItem, EntityKind
from infrastructure.read_models.filters import OWN_RORS_SQL
from infrastructure.sql_fragments import has_author_role


class EntitySql(NamedTuple):
    """Fragments SQL d'un type d'entité (valeurs figées, aucune injection)."""

    # Table de l'entité avec son alias, pour lire un libellé par identifiant.
    table: str
    id: str
    label: str
    # Jointure depuis `publications p` vers l'entité.
    join: str
    # Type SQL de l'identifiant, pour lire un libellé à partir de l'identifiant reçu en texte.
    id_type: str = "integer"
    # Décompte des publications par entité. `COUNT(*)` suffit quand la jointure rend une ligne par couple publication–entité.
    publication_count: str = "COUNT(*)"


# La revue sort de `publications.serial_id`, l'éditeur de `publications.publisher_id`. L'organisation partenaire est un ROR des auteurs, ancêtres compris (`publication_rors`), hors les ROR propres aux structures `:own_structure_ids`, nommé par le référentiel ROR. L'auteur passe par les groupes de contributions sources rattachés à une personne ; une personne rejetée n'est pas proposée. Le sujet passe par `publication_subjects`, qui porte une ligne par source pour un même couple publication–sujet.
ENTITY_SQL: dict[EntityKind, EntitySql] = {
    "serial": EntitySql(
        table="serials j",
        id="j.id",
        label="j.title",
        join="JOIN serials j ON j.id = p.serial_id",
    ),
    "publisher": EntitySql(
        table="publishers pub",
        id="pub.id",
        label="pub.name",
        join="JOIN publishers pub ON pub.id = p.publisher_id",
    ),
    "person": EntitySql(
        table="persons pe",
        id="pe.id",
        label="pe.first_name || ' ' || pe.last_name",
        join=(
            f"JOIN contributions au ON au.publication_id = p.id AND {has_author_role('au')} "
            "JOIN persons pe ON pe.id = au.person_id AND pe.exclusion IS NULL"
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
        publication_count="COUNT(DISTINCT p.id)",
    ),
    "partner": EntitySql(
        table="ror_organizations ro",
        id="ro.ror_id",
        label="ro.name",
        join=(
            "JOIN publication_rors pr ON pr.publication_id = p.id "
            f"AND pr.ror_id NOT IN ({OWN_RORS_SQL}) "
            "JOIN ror_organizations ro ON ro.ror_id = pr.ror_id"
        ),
        id_type="text",
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
    own_structure_ids: list[int],
) -> list[EntityFacetItem]:
    """Entités `kind` les plus représentées parmi les publications `p` qui satisfont `where_sql`.

    Le décompte porte sur les publications distinctes. Un terme de recherche d'au moins deux caractères filtre les entités par nom. Les organisations partenaires excluent les ROR propres aux structures `own_structure_ids`.
    """
    sql = ENTITY_SQL[kind]
    name_filter, name_binds = entity_name_clause(sql.label, search)
    params: dict[str, object] = {
        **binds,
        **name_binds,
        "lim": limit,
        "own_structure_ids": own_structure_ids,
    }
    conn.execute(text("SET LOCAL jit = off"))
    rows = conn.execute(
        text(f"""
            SELECT {sql.id} AS id, {sql.label} AS label, {sql.publication_count} AS n
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
