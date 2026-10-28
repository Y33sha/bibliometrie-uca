"""Identifiants d'un enregistrement source lus dans `source_record_identifiers`, en tableau JSON joint à la ligne de l'enregistrement source."""

from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
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
