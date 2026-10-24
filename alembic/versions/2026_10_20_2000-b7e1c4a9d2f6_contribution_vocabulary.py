"""Vocabulaire des enregistrements sources et des contributions

Revision ID: b7e1c4a9d2f6
Revises: 6a2d9e4b7c51
Create Date: 2026-10-20 20:00:00.000000

Renomme les tables, vues, colonnes, contraintes, index et séquences selon le vocabulaire du code : `source_publications` → `source_records`, `source_authorships` → `source_contributions`, `authorships` → `contributions`, `author_identifying_keys` → `contributor_information`, `persons_rh` → `hr_records`, `structure_tutelles` → `structure_parents`, `pub_year` → `publication_year`, `pub_count` → `publication_count`. Les noms d'index abrégés passent en mots entiers. La migration réécrit aussi la fonction `regroup_identifier_publications`, les commentaires des objets, la phase `authorships` de l'historique des exécutions et les événements `authorship.*` du journal d'audit.
"""

from collections.abc import Callable, Iterable, Sequence

from sqlalchemy import text

from alembic import op

revision: str = "b7e1c4a9d2f6"
down_revision: str | Sequence[str] | None = "6a2d9e4b7c51"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fragments de nom, du plus spécifique au plus général. Aucun nom antérieur ne contient un
# fragment cible : la chaîne inverse, dans le même ordre, rend le nom d'origine.
_FRAGMENTS = (
    ("grouped_source_authorships", "source_contribution_group_members"),
    ("confirmed_authorships", "confirmed_source_contributions"),
    ("matched_signatures", "matched_source_contributions"),
    ("author_identifying_keys", "contributor_information"),
    ("source_authorship", "source_contribution"),
    ("source_publication", "source_record"),
    ("authorship", "contribution"),
    ("persons_rh", "hr_records"),
    ("structure_tutelles", "structure_parents"),
    ("pub_year", "publication_year"),
    ("pub_count", "publication_count"),
)

# Noms entiers, hors fragments : noms abrégés, noms trop longs, et noms de `identity_id`, dont la cible
# `contributor_information_id` est le début d'autres noms (`contributor_information_idref_idx`).
_ABBREVIATIONS = {
    "identity_id": "contributor_information_id",
    "source_authorships_identity_id_fkey": "source_contributions_contributor_information_id_fkey",
    "source_authorships_identity_id_not_null": "source_contributions_contributor_information_id_not_null",
    "idx_sa_countries_dirty": "idx_source_contributions_countries_dirty",
    "idx_sa_identity": "idx_source_contributions_contributor_information",
    "idx_sa_in_perimeter": "idx_source_contributions_in_perimeter",
    "idx_sa_orphan_in_perimeter": "idx_source_contributions_orphan_in_perimeter",
    "idx_sa_person": "idx_source_contributions_person",
    "idx_sa_pub_person": "idx_source_contributions_record_person",
    "idx_source_pubs_countries": "idx_source_records_countries",
    "idx_source_pubs_doi": "idx_source_records_doi",
    "idx_source_pubs_external_ids": "idx_source_records_external_ids",
    "idx_source_pubs_first_hal_id": "idx_source_records_first_hal_id",
    "idx_source_pubs_hal_collections": "idx_source_records_hal_collections",
    "idx_source_pubs_journal": "idx_source_records_journal",
    "idx_source_pubs_keys_dirty": "idx_source_records_keys_dirty",
    "idx_source_pubs_metadata_block": "idx_source_records_metadata_block",
    "idx_source_pubs_nnt": "idx_source_records_nnt",
    "idx_source_pubs_pmid": "idx_source_records_pmid",
    "idx_source_pubs_pub": "idx_source_records_publication",
    "idx_source_pubs_staging": "idx_source_records_staging",
    "idx_source_pubs_title_normalized_trgm": "idx_source_records_title_normalized_trgm",
    "idx_authorships_pub": "idx_contributions_publication",
    "idx_authorships_pub_uca": "idx_contributions_publication_uca",
    "idx_pub_countries": "idx_publications_countries",
    "idx_pub_title_trgm": "idx_publications_title_trgm",
    "idx_pub_nf_publisher": "idx_publisher_name_forms_publisher",
    "idx_apc_pub": "idx_apc_payments_publication",
    "idx_publication_relations_target_pub": "idx_publication_relations_target_publication",
    "publication_structures_pub_struct": "publication_structures_publication_structure",
    # Noms par défaut que Postgres tronque à 63 caractères.
    "source_authorship_hal_structures_source_authorship_id_not_null": "source_contribution_hal_structu_source_contribution_id_not_null",
    "grouped_source_authorships_source_authorship_id_not_null": "source_contribution_group_membe_source_contribution_id_not_null",
    "source_authorship_addresses_source_authorship_id_address_id_key": "source_contribution_addresses_key",
    "source_authorships_pub_pos_key": "source_contributions_record_position_key",
    "grouped_source_authorships_group_notice_uq": "source_contribution_group_members_group_record_uq",
    "rejected_authorships_by_notice_source_publication_id_not_null": "rejected_contributions_source_record_id_not_null",
    "rejected_authorships_by_notice_person_id_not_null": "rejected_contributions_person_id_not_null",
    "rejected_authorships_by_notice_created_at_not_null": "rejected_contributions_created_at_not_null",
}


def _forward(name: str) -> str:
    if name in _ABBREVIATIONS:
        return _ABBREVIATIONS[name]
    for old, new in _FRAGMENTS:
        name = name.replace(old, new)
    return name


_REVERSED_ABBREVIATIONS = {new: old for old, new in _ABBREVIATIONS.items()}


def _backward(name: str) -> str:
    if name in _REVERSED_ABBREVIATIONS:
        return _REVERSED_ABBREVIATIONS[name]
    for old, new in _FRAGMENTS:
        name = name.replace(new, old)
    return name


_SYSTEM_SCHEMAS = "('pg_catalog', 'information_schema', 'pg_toast')"
_KIND = {
    "r": "TABLE",
    "p": "TABLE",
    "m": "MATERIALIZED VIEW",
    "v": "VIEW",
    "i": "INDEX",
    "S": "SEQUENCE",
}


def _rename_objects(rename: Callable[[str], str]) -> None:
    """Applique `rename` aux colonnes, aux contraintes, puis aux relations, index et séquences."""
    conn = op.get_bind()
    columns = conn.execute(
        text(f"""
            SELECT n.nspname, c.relname, c.relkind, a.attname
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname NOT IN {_SYSTEM_SCHEMAS}
              AND c.relkind IN ('r', 'p', 'm', 'v')
              AND a.attnum > 0 AND NOT a.attisdropped
        """)
    ).all()
    for schema, relation, kind, column in columns:
        if rename(column) != column:
            op.execute(
                f'ALTER {_KIND[kind]} "{schema}"."{relation}" '
                f'RENAME COLUMN "{column}" TO "{rename(column)}"'
            )
    constraints = conn.execute(
        text(f"""
            SELECT n.nspname, c.relname, con.conname
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname NOT IN {_SYSTEM_SCHEMAS}
        """)
    ).all()
    for schema, relation, constraint in constraints:
        if rename(constraint) != constraint:
            op.execute(
                f'ALTER TABLE "{schema}"."{relation}" '
                f'RENAME CONSTRAINT "{constraint}" TO "{rename(constraint)}"'
            )
    relations = conn.execute(
        text(f"""
            SELECT n.nspname, c.relname, c.relkind
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname NOT IN {_SYSTEM_SCHEMAS}
              AND c.relkind IN ('r', 'p', 'm', 'v', 'i', 'S')
        """)
    ).all()
    for schema, relation, kind in relations:
        if rename(relation) != relation:
            op.execute(
                f'ALTER {_KIND[kind]} "{schema}"."{relation}" RENAME TO "{rename(relation)}"'
            )


_REGROUP_FUNCTION = """
    CREATE OR REPLACE FUNCTION public.regroup_identifier_publications(id_type text, id_value text)
    RETURNS void LANGUAGE sql AS $$
        UPDATE publications.publications p SET {dirty} = true
        FROM sources.{records} sr
        JOIN sources.{contributions} sc ON sc.{record_id} = sr.id
        JOIN sources.{information} ci ON ci.id = sc.{information_id}
        WHERE p.id = sr.publication_id AND NOT p.{dirty}
          AND ci.{identifiers} ? id_type
          AND ci.{identifiers} ->> id_type = id_value
    $$
"""

_NEW_NAMES = {
    "dirty": "contributions_dirty",
    "records": "source_records",
    "contributions": "source_contributions",
    "record_id": "source_record_id",
    "information": "contributor_information",
    "information_id": "contributor_information_id",
    "identifiers": "identifiers",
}
_OLD_NAMES = {
    "dirty": "authorships_dirty",
    "records": "source_publications",
    "contributions": "source_authorships",
    "record_id": "source_publication_id",
    "information": "author_identifying_keys",
    "information_id": "identity_id",
    "identifiers": "person_identifiers",
}

# (objet, commentaire avant, commentaire après), objets nommés après la migration.
_COMMENTS = (
    (
        "COLUMN ops.audit_log.aggregate_type",
        "Type de l'entité affectée : person, publication, structure, journal, publisher, authorship.",
        "Type de l'entité affectée : address, journal, perimeter, person, publication, structure.",
    ),
    (
        "TABLE sources.source_contribution_rors",
        "ROR attribués par la source à une signature, rattachés à l'adresse de leur affiliation, ou à la seule signature quand l'affiliation est sans texte (address_id vide). ror_id est sans clé étrangère vers ror_organizations : une source peut citer un ROR absent du dump importé.",
        "ROR attribués par la source à une contribution source, rattachés à l'adresse de leur affiliation, ou à la seule contribution source quand l'affiliation est sans texte (address_id vide). ror_id est sans clé étrangère vers ror_organizations : une source peut citer un ROR absent du dump importé.",
    ),
    (
        "COLUMN sources.source_contributions.neutralized_identifiers",
        'Identifiants de l\'identité que la résolution des personnes ignore pour cette signature, avec leur motif : {"orcid": "shared"}.',
        'Identifiants des informations du contributeur que la résolution des personnes ignore pour cette contribution source, avec leur motif : {"orcid": "shared"}.',
    ),
    (
        "COLUMN sources.source_contributions.countries",
        "Pays de la signature : pays retenus de ses adresses, de ses organisations ROR sans adresse et de ses structures HAL.",
        "Pays de la contribution source : pays retenus de ses adresses, de ses organisations ROR sans adresse et de ses structures HAL.",
    ),
    (
        "COLUMN sources.source_contributions.collective",
        "Signature collective (collaboration, consortium, groupe d'étude…), posée par la normalisation d'après le signal de la source ou d'après le nom.",
        "Contribution source collective (collaboration, consortium, groupe d'étude…), posée par la normalisation d'après le signal de la source ou d'après le nom.",
    ),
    (
        "COLUMN sources.source_contributions.duplicate_of",
        "Doublon d'auteur : signature qui répète, dans la liste d'auteurs de sa notice, la signature référencée. Écrite par la phase author_grouping.",
        "Doublon d'auteur : contribution source qui répète, dans la liste d'auteurs de son enregistrement source, la contribution source référencée. Écrite par la phase author_grouping.",
    ),
    (
        "COLUMN sources.source_records.authors_hash",
        "Empreinte de la partie auteurs du payload source, à la dernière synchronisation des signatures.",
        "Empreinte de la partie auteurs du payload source, à la dernière synchronisation des contributions sources.",
    ),
    (
        "COLUMN sources.source_records.author_count",
        "Signatures de la notice qui ont le rôle author et ne sont pas collectives, telles que la source les donne.",
        "Contributions sources de l'enregistrement source qui ont le rôle author et ne sont pas collectives, telles que la source les donne.",
    ),
    (
        "COLUMN sources.source_records.distinct_author_count",
        "Noms complets normalisés distincts parmi les signatures comptées par author_count.",
        "Noms complets normalisés distincts parmi les contributions sources comptées par author_count.",
    ),
    (
        "TABLE publications.source_contribution_group_members",
        "Appartenance d'une signature à son groupe. method : origine du lien. score et margin, en bits, pour method = model : poids de Fellegi-Sunter du lien, et écart à la meilleure autre possibilité de l'affectation.",
        "Appartenance d'une contribution source à son groupe. method : origine du lien. score et margin, en bits, pour method = model : poids de Fellegi-Sunter du lien, et écart à la meilleure autre possibilité de l'affectation.",
    ),
    (
        "TABLE publications.source_contribution_groups",
        "Signatures d'un même auteur dans une publication, avec au maximum une signature par notice. reference_position : position dans la liste la plus longue. Une personne correspond au maximum à un groupe par publication.",
        "Contributions sources d'un même auteur dans une publication, avec au maximum une contribution source par enregistrement source. reference_position : position dans la liste la plus longue. Une personne correspond au maximum à un groupe par publication.",
    ),
    (
        "MATERIALIZED VIEW publications.publication_author_alignment",
        "Recouvrement des listes d'auteurs des publications à plusieurs notices. matched_signatures : signatures d'auteur qui ont un correspondant dans une autre notice.",
        "Recouvrement des listes d'auteurs des publications à plusieurs enregistrements sources. matched_source_contributions : contributions sources qui ont un correspondant dans un autre enregistrement source.",
    ),
    (
        "COLUMN publications.publications.contributions_dirty",
        "Groupes de signatures à recalculer : une notice a rejoint ou quitté la publication, ou ses signatures ont changé.",
        "Groupes de contributions sources à recalculer : un enregistrement source a rejoint ou quitté la publication, ou ses contributions sources ont changé.",
    ),
)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _rename_sql(expression: str, pairs: Iterable[tuple[str, str]]) -> str:
    for old, new in pairs:
        expression = f"replace({expression}, {_sql_literal(old)}, {_sql_literal(new)})"
    return expression


_HISTORY_FRAGMENTS = (
    ("source_authorship", "source_contribution"),
    ("source_publication", "source_record"),
    ("authorship", "contribution"),
)


def _rename_history(pairs: Sequence[tuple[str, str]], old_phase: str, new_phase: str) -> None:
    """Renomme la phase de l'historique, les événements d'audit et les clés de leur payload."""
    op.execute(
        f"UPDATE ops.pipeline_phase_executions SET phase = '{new_phase}' WHERE phase = '{old_phase}'"
    )
    op.execute(
        f"UPDATE ops.audit_log SET event_type = {_rename_sql('event_type', pairs)} "
        f"WHERE event_type <> {_rename_sql('event_type', pairs)}"
    )
    op.execute(f"""
        UPDATE ops.audit_log SET payload = (
            SELECT jsonb_object_agg({_rename_sql("key", pairs)}, value)
            FROM jsonb_each(payload)
        )
        WHERE EXISTS (
            SELECT 1 FROM jsonb_object_keys(payload) AS k(key)
            WHERE k.key <> {_rename_sql("k.key", pairs)}
        )
    """)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sources.author_identifying_keys "
        "RENAME COLUMN person_identifiers TO identifiers"
    )
    _rename_objects(_forward)
    op.execute("ALTER TYPE public.perimeter_evidence RENAME VALUE 'rh_identity' TO 'hr_record'")
    op.execute(_REGROUP_FUNCTION.format(**_NEW_NAMES))
    for target, _, comment in _COMMENTS:
        op.execute(f"COMMENT ON {target} IS {_sql_literal(comment)}")
    _rename_history(_HISTORY_FRAGMENTS, "authorships", "contributions")


def downgrade() -> None:
    _rename_history([(new, old) for old, new in _HISTORY_FRAGMENTS], "contributions", "authorships")
    for target, comment, _ in _COMMENTS:
        op.execute(f"COMMENT ON {target} IS {_sql_literal(comment)}")
    op.execute("ALTER TYPE public.perimeter_evidence RENAME VALUE 'hr_record' TO 'rh_identity'")
    _rename_objects(_backward)
    op.execute(
        "ALTER TABLE sources.author_identifying_keys "
        "RENAME COLUMN identifiers TO person_identifiers"
    )
    op.execute(_REGROUP_FUNCTION.format(**_OLD_NAMES))
