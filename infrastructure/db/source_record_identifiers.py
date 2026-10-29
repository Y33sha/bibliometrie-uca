"""Lecture de `source_record_identifiers` : identifiants d'un enregistrement source en tableau JSON joint à sa ligne, et conditions SQL sur un identifiant aliasé."""

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.sources.registry import AGGREGATOR_SOURCES
from infrastructure.sql_fragments import case_priority, raw_column


def first_of_its_type_sql(identifier: str) -> str:
    """Condition SQL : l'identifiant aliasé `identifier` est actif, et premier des identifiants actifs de son type dans son enregistrement source, par rôle puis par valeur (`by_role`). La collation `C` compare les valeurs comme Python."""
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


def related_doi_sql(identifier: str, source_record: str) -> str:
    """Condition SQL : l'identifiant aliasé `identifier` est un DOI actif autre que le DOI d'avant correction de l'enregistrement source aliasé `source_record`."""
    return (
        f"{identifier}.id_type = '{SourceIdentifierType.DOI}' AND {identifier}.removed_by IS NULL"
        f" AND {identifier}.id_value IS DISTINCT FROM {raw_column('doi', source_record)}"
    )


def serial_doi_sql(identifier: str, source_record: str) -> str:
    """Condition SQL : l'identifiant aliasé `identifier` est un DOI actif que l'enregistrement source aliasé `source_record` donne avec sa revue.

    Ce sont ses DOI `primary` ou `derived`. A défaut, ce sont ses DOI `secondary`, sauf chez un agrégateur : chez OpenAlex, un DOI `secondary` est souvent celui d'une copie de repository.
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
    """Expression SQL : identifiants de l'enregistrement source d'identifiant `source_record`, avec leur rôle et leur statut, en tableau JSON trié par type puis par valeur."""
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
    """Identifiants lus par `identifiers_json_sql`."""
    return tuple(
        SourceIdentifier(
            SourceIdentifierType(str(i["id_type"])),
            str(i["value"]),
            SourceIdentifierRole(str(i["role"])),
            i["removed_by"],
        )
        for i in raw
    )
