"""Lecture de `source_record_identifiers` : identifiants d'un enregistrement source en tableau JSON joint à sa ligne, et conditions SQL sur un identifiant aliasé."""

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.sources.registry import AGGREGATOR_SOURCES
from infrastructure.sql_fragments import case_priority


def first_of_its_type_sql(identifier: str) -> str:
    """Renvoie la condition SQL : l'identifiant `identifier` est actif, et premier des identifiants actifs de son type dans son enregistrement source.

    L'ordre suit le rôle puis la valeur (`by_role`). La collation `C` compare les valeurs comme Python.

    Args:
        identifier: alias SQL de l'identifiant.
    """
    rank = case_priority(tuple(SourceIdentifierRole), "{a}.role")
    # noqa S608 : `identifier` est un alias de la requête hôte, jamais une entrée.
    return (
        f"{identifier}.removed_by IS NULL AND NOT EXISTS ("  # noqa: S608
        "SELECT 1 FROM source_record_identifiers x"
        f" WHERE x.source_record_id = {identifier}.source_record_id"
        f" AND x.id_type = {identifier}.id_type AND x.removed_by IS NULL"
        f' AND ({rank.format(a="x")}, x.id_value COLLATE "C")'
        f' < ({rank.format(a=identifier)}, {identifier}.id_value COLLATE "C"))'
    )


def source_record_doi_sql(source_record: str) -> str:
    """Renvoie l'expression SQL du DOI affiché de l'enregistrement source, NULL sans DOI.

    Le DOI affiché est le premier des DOI actifs de rôle autre que `related`, par rôle puis par valeur (`first_of_its_type_sql`).

    Args:
        source_record: alias SQL de l'enregistrement source.
    """
    return (
        "(SELECT d.id_value FROM source_record_identifiers d"  # noqa: S608
        f" WHERE d.source_record_id = {source_record}.id"
        f" AND d.id_type = '{SourceIdentifierType.DOI}'"
        f" AND d.role <> '{SourceIdentifierRole.RELATED}' AND {first_of_its_type_sql('d')})"
    )


def serial_doi_sql(identifier: str, source_record: str) -> str:
    """Renvoie la condition SQL : l'identifiant `identifier` est un DOI actif donné par l'enregistrement source `source_record` avec sa revue.

    Ce sont ses DOI `primary` ou `derived`. À défaut, ce sont ses DOI `secondary`, sauf chez un agrégateur. Chez OpenAlex, un DOI `secondary` désigne souvent une copie de repository.

    Args:
        identifier: alias SQL de l'identifiant.
        source_record: alias SQL de l'enregistrement source.
    """
    aggregators = ", ".join(f"'{s.value}'" for s in sorted(AGGREGATOR_SOURCES))
    strong = f"'{SourceIdentifierRole.PRIMARY}', '{SourceIdentifierRole.DERIVED}'"
    # noqa S608 : `identifier` et `source_record` sont des alias de la requête hôte, jamais une entrée.
    return (
        f"{identifier}.id_type = '{SourceIdentifierType.DOI}' AND {identifier}.removed_by IS NULL"  # noqa: S608
        f" AND ({identifier}.role IN ({strong})"
        f" OR ({identifier}.role = '{SourceIdentifierRole.SECONDARY}'"
        f" AND {source_record}.source::text NOT IN ({aggregators})"
        " AND NOT EXISTS (SELECT 1 FROM source_record_identifiers x"
        f" WHERE x.source_record_id = {identifier}.source_record_id"
        f" AND x.id_type = '{SourceIdentifierType.DOI}' AND x.removed_by IS NULL"
        f" AND x.role IN ({strong}))))"
    )


def identifiers_json_sql(source_record: str) -> str:
    """Renvoie l'expression SQL des identifiants de l'enregistrement source, avec leur rôle et leur statut, en tableau JSON trié par type puis par valeur.

    Args:
        source_record: expression SQL de l'identifiant de l'enregistrement source.
    """
    return f"""
        COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id_type', i.id_type, 'value', i.id_value, 'role', i.role,
                'removed_by', i.removed_by
            ) ORDER BY i.id_type, i.id_value)
            FROM source_record_identifiers i WHERE i.source_record_id = {source_record}
        ), '[]'::jsonb)
    """  # noqa: S608 — `source_record` est une expression de la requête hôte, jamais une entrée


def parse_identifiers(raw: list[dict[str, str | None]]) -> tuple[SourceIdentifier, ...]:
    """Renvoie les identifiants lus par `identifiers_json_sql`."""
    return tuple(
        SourceIdentifier(
            SourceIdentifierType(str(i["id_type"])),
            str(i["value"]),
            SourceIdentifierRole(str(i["role"])),
            i["removed_by"],
        )
        for i in raw
    )
