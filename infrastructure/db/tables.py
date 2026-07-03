"""MetaData SQLAlchemy — source de vérité du schéma Postgres.

Description complète des tables, indexes, contraintes uniques, CHECK
constraints et comments. Sert :
- au query-building côté SQLAlchemy Core (`select(config.c.key)…`),
- à `alembic revision --autogenerate` (comparaison MetaData ↔ DB).

Les Foreign Keys ne sont volontairement pas déclarées (pattern
query-building, pas modélisation relationnelle complète). Le filtre
`include_object` dans `alembic/env.py` empêche autogenerate de les
considérer.

`infrastructure/db/schema.sql` reste un snapshot descriptif lisible,
régénéré par `python -m infrastructure.db.dump_schema`. Le test
`tests/integration/infrastructure/db/test_sqlalchemy_smoke.py`
vérifie la cohérence MetaData ↔ DB sur les colonnes.
"""

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    Index,
    Integer,
    MetaData,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM as PgEnum, JSONB, REAL

metadata = MetaData()


audit_log = Table(
    "audit_log",
    metadata,
    Column(
        "id",
        BigInteger,
        primary_key=True,
    ),
    Column(
        "event_type",
        Text,
        nullable=False,
        comment=(
            "Type d'événement, notation pointée : person.merged, "
            "publication.excluded, structure.deleted, etc."
        ),
    ),
    Column(
        "aggregate_type",
        Text,
        nullable=False,
        comment=(
            "Type de l'entité affectée : person, publication, structure, "
            "journal, publisher, authorship."
        ),
    ),
    Column(
        "aggregate_id",
        Integer,
        comment=(
            "ID de l'entité affectée, NULL si l'entité a été supprimée et "
            "n'a pas d'équivalent survivant."
        ),
    ),
    Column(
        "payload",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
        comment=(
            "Données utiles pour l'audit : source_id d'une fusion, champs modifiés, raison, etc."
        ),
    ),
    Column(
        "user_id",
        Text,
        comment=(
            "Utilisateur admin authentifié ayant déclenché l'opération "
            "(middleware auth). NULL théoriquement impossible quand l'entrée "
            "est écrite."
        ),
    ),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Index("audit_log_aggregate_idx", "aggregate_type", "aggregate_id"),
    Index("audit_log_created_at_idx", text("created_at DESC")),
    Index("audit_log_event_type_idx", "event_type", text("created_at DESC")),
    comment=(
        "Trace des opérations destructives/décisionnelles déclenchées via "
        "l'admin HTTP. Les opérations du pipeline ne sont pas auditées."
    ),
)


config = Table(
    "config",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", JSONB, nullable=False),
    Column("description", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)


perimeters = Table(
    "perimeters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column(
        "structure_ids",
        ARRAY(Integer),
        nullable=False,
        server_default=text("'{}'::integer[]"),
    ),
    UniqueConstraint("code", name="perimeters_code_key"),
)


# Clôture transitive (est_tutelle_de) du périmètre, matérialisée et maintenue
# par `refresh_perimeter_structures`. FK CASCADE des deux côtés (déclarées en
# migration, omises ici comme pour les autres tables de jointure).
perimeter_structures = Table(
    "perimeter_structures",
    metadata,
    Column("perimeter_id", Integer, nullable=False),
    Column("structure_id", Integer, nullable=False),
    PrimaryKeyConstraint(
        "perimeter_id",
        "structure_id",
        name="perimeter_structures_pkey",
    ),
    Index("idx_ps_structure_id", "structure_id"),
)


# Enum Postgres `structure_type` — déclaré tel quel côté SA pour que les
# inserts produisent un cast typé (sinon Postgres rejette VARCHAR ↛ enum).
# `create_type=False` : l'enum est créé par les migrations SQL, pas par SA.
structure_type_enum = PgEnum(
    "universite",
    "chu",
    "ecole",
    "labo",
    "equipe",
    "site",
    "autre",
    "onr",
    name="structure_type",
    create_type=False,
)

publisher_type_enum = PgEnum(
    "commercial",
    "learned_society",
    "academic_institution",
    "repository",
    "aggregator",
    "unknown",
    name="publisher_type",
    create_type=False,
)

journal_type_enum = PgEnum(
    "journal",
    "proceedings",
    "repository",
    "book_series",
    "preprint_server",
    "media",
    "ebook_platform",
    "unknown",
    name="journal_type",
    create_type=False,
)


structures = Table(
    "structures",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("acronym", Text),
    Column("structure_type", structure_type_enum, nullable=False),
    Column("ror_id", Text),
    Column("rnsr_id", Text),
    Column("hal_collection", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("api_ids", JSONB),
    UniqueConstraint("code", name="structures_code_key"),
    Index("idx_structures_type", "structure_type"),
)


structure_relations = Table(
    "structure_relations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("parent_id", Integer, nullable=False),
    Column("child_id", Integer, nullable=False),
    Column("relation_type", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint(
        "parent_id",
        "child_id",
        "relation_type",
        name="structure_relations_parent_id_child_id_relation_type_key",
    ),
    Index("idx_struct_rel_child", "child_id"),
    Index("idx_struct_rel_parent", "parent_id"),
)


structure_name_forms = Table(
    "structure_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("structure_id", Integer, nullable=False),
    Column("form_text", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("is_word_boundary", Boolean, nullable=False, server_default="false"),
    Column("requires_context_of", ARRAY(Integer)),
    Column("is_excluding", Boolean, nullable=False, server_default="false"),
    UniqueConstraint("structure_id", "form_text", name="uq_snf_structure_form"),
    Index("idx_structure_name_forms_structure", "structure_id"),
)


journals = Table(
    "journals",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text, nullable=False),
    Column("issn", Text),
    Column("eissn", Text),
    Column("issnl", Text),
    Column("publisher_id", Integer),
    Column("openalex_id", Text),
    Column("is_in_doaj", Boolean, server_default="false"),
    Column("is_predatory", Boolean, server_default="false"),
    Column("apc_amount", Numeric(10, 2)),
    Column("apc_currency", Text, server_default="EUR"),
    Column("oa_model", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("journal_type", journal_type_enum, server_default="unknown"),
    Column("is_academic", Boolean, server_default="true"),
    Column("doi_prefix", Text),
    Column("doaj_payload", JSONB),
    Column("doaj_imported_at", DateTime(timezone=True)),
    # Compte matérialisé des publications in-perimeter de la revue. Maintenu par le
    # pipeline (après le rollup in_perimeter) + aux fusions admin. Évite de re-scanner
    # publications pour le filtre `with_pubs` / le tri / l'affichage.
    Column("pub_count", Integer, nullable=False, server_default="0"),
    UniqueConstraint("openalex_id", name="journals_openalex_id_key"),
    Index(
        "idx_journals_doi_prefix",
        "doi_prefix",
        postgresql_where=text("doi_prefix IS NOT NULL"),
    ),
    Index("idx_journals_eissn", "eissn"),
    Index("idx_journals_issn", "issn"),
    Index("idx_journals_issnl", "issnl"),
    Index("idx_journals_publisher", "publisher_id"),
    Index("idx_journals_titlenorm", "title_normalized"),
)


journal_name_forms = Table(
    "journal_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("journal_id", Integer, nullable=False),
    Column("form_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("publisher_id", Integer),
    UniqueConstraint("form_normalized", "publisher_id", name="uq_jnl_nf_form_publisher"),
    Index("idx_jnl_nf_journal", "journal_id"),
)


publishers = Table(
    "publishers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_normalized", Text, nullable=False),
    Column("openalex_id", Text),
    Column("country", Text),
    Column("ror", Text),
    Column("is_predatory", Boolean, server_default="false"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column(
        "publisher_type",
        publisher_type_enum,
        nullable=False,
        server_default="unknown",
    ),
    # Compte matérialisé des publications in-perimeter de l'éditeur (= somme de ses
    # revues). Maintenu par le pipeline + aux fusions admin. Cf. `journals.pub_count`.
    Column("pub_count", Integer, nullable=False, server_default="0"),
    UniqueConstraint("openalex_id", name="publishers_openalex_id_key"),
    Index("idx_publishers_name_norm", "name_normalized"),
    Index(
        "idx_publishers_name_trgm",
        "name",
        postgresql_ops={"name": "gin_trgm_ops"},
        postgresql_using="gin",
    ),
)


publisher_name_forms = Table(
    "publisher_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("publisher_id", Integer, nullable=False),
    Column("form_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("form_normalized", name="publisher_name_forms_form_normalized_key"),
    Index("idx_pub_nf_publisher", "publisher_id"),
)


doi_prefixes = Table(
    "doi_prefixes",
    metadata,
    Column("prefix", Text, primary_key=True),
    Column("ra", Text, nullable=False),
    Column("publisher_id", Integer),
    Column("publisher_name_raw", Text),
    Column("publisher_name_normalized", Text),
    Column("crossref_member_id", Integer),
    Column("client_name_raw", Text),
    Column("client_name_normalized", Text),
    Column("datacite_client_symbol", Text),
    Column("fetched_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("publisher_checked_at", DateTime(timezone=True)),
    Index("idx_doi_prefixes_ra", "ra"),
    Index(
        "idx_doi_prefixes_publisher_pending",
        "prefix",
        postgresql_where=text("publisher_id IS NULL AND publisher_checked_at IS NULL"),
    ),
    Index(
        "idx_doi_prefixes_publisher",
        "publisher_id",
        postgresql_where=text("publisher_id IS NOT NULL"),
    ),
    Index(
        "idx_doi_prefixes_publisher_name_normalized",
        "publisher_name_normalized",
        postgresql_where=text("publisher_id IS NULL"),
    ),
    Index(
        "idx_doi_prefixes_client_name_normalized",
        "client_name_normalized",
        postgresql_where=text("client_name_normalized IS NOT NULL"),
    ),
    Index(
        "idx_doi_prefixes_datacite_client_symbol",
        "datacite_client_symbol",
        postgresql_where=text("datacite_client_symbol IS NOT NULL"),
    ),
)


# ── Enums Postgres communs ────────────────────────────────────────


identifier_status_enum = PgEnum(
    "pending",
    "confirmed",
    "rejected",
    name="identifier_status",
    create_type=False,
)

identifier_origin_enum = PgEnum(
    "manual",
    "auto",
    name="identifier_origin",
    create_type=False,
)

source_type_enum = PgEnum(
    "hal",
    "openalex",
    "wos",
    "scanr",
    "theses",
    "crossref",
    name="source_type",
    create_type=False,
)

oa_type_enum = PgEnum(
    "gold",
    "hybrid",
    "bronze",
    "green",
    "closed",
    "unknown",
    "diamond",
    name="oa_type",
    create_type=False,
)

doc_type_enum = PgEnum(
    "article",
    "conference_paper",
    "book",
    "book_chapter",
    "thesis",
    "ongoing_thesis",
    "preprint",
    "review",
    "editorial",
    "report",
    "peer_review",
    "other",
    "dataset",
    "software",
    "patent",
    "hdr",
    "memoir",
    "poster",
    "letter",
    "erratum",
    "retraction",
    "book_review",
    "data_paper",
    "proceedings",
    name="doc_type",
    create_type=False,
)


# ── Adresses ──────────────────────────────────────────────────────


addresses = Table(
    "addresses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("raw_text", Text, nullable=False),
    Column("normalized_text", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("pub_count", Integer, server_default="0"),
    Column("countries", ARRAY(CHAR(2))),
    Column("suggested_countries", ARRAY(CHAR(2))),
    # Refresh pays incrémental : True = `countries` vient de changer, les `sa`
    # liés sont à recalculer. Posé gratuitement à l'écriture de `countries`
    # (detect / institution), dérivé par JOIN au refresh, purgé en fin de cascade.
    Column("countries_dirty", Boolean, nullable=False, server_default="false"),
    # Index UNIQUE sur expression md5(raw_text) — complété à la main, hors
    # de portée de --autogenerate qui ne sait pas représenter l'expression.
    Index("addresses_raw_text_key", text("md5(raw_text)"), unique=True),
    Index(
        "idx_addr_sug_countries",
        "suggested_countries",
        postgresql_using="gin",
        postgresql_where=text("suggested_countries IS NOT NULL"),
    ),
    Index(
        "idx_addresses_countries",
        "countries",
        postgresql_using="gin",
        postgresql_where=text("countries IS NOT NULL"),
    ),
    Index(
        "idx_addresses_normalized_text_trgm",
        "normalized_text",
        postgresql_ops={"normalized_text": "gin_trgm_ops"},
        postgresql_using="gin",
    ),
)


place_name_forms = Table(
    "place_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    # `iso_code` en minuscule (canonique, cf. countries.code / addresses.countries).
    Column("iso_code", Text, nullable=False),
    Column("form_normalized", Text, nullable=False),
    # `country` (noms de pays, détectés en fin d'adresse) | `institution` /
    # `city` (lieux détectés n'importe où, via la passe place). Défaut `country` :
    # legacy + résolution nom-de-pays → ISO.
    Column("kind", Text, nullable=False, server_default="country"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("form_normalized", name="place_name_forms_form_normalized_key"),
    Index("idx_pnf_iso", "iso_code"),
    CheckConstraint(
        "kind IN ('country', 'institution', 'city')", name="place_name_forms_kind_check"
    ),
)


address_structures = Table(
    "address_structures",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("address_id", Integer, nullable=False),
    Column("structure_id", Integer, nullable=False),
    Column("matched_form_id", Integer),
    Column("is_confirmed", Boolean),
    UniqueConstraint(
        "address_id", "structure_id", name="address_structures_address_id_structure_id_key"
    ),
    Index("idx_addr_struct_address", "address_id"),
    Index(
        "idx_addr_struct_filter",
        "structure_id",
        "address_id",
        postgresql_include=["matched_form_id", "is_confirmed"],
    ),
    Index("idx_addr_struct_structure", "structure_id"),
)


# ── Authorships (vérité + sources) ────────────────────────────────


authorships = Table(
    "authorships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("publication_id", Integer, nullable=False),
    Column("person_id", Integer),
    Column("author_position", SmallInteger),
    Column("in_perimeter", Boolean, server_default="false"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("is_corresponding", Boolean),
    Column("roles", ARRAY(Text)),
    UniqueConstraint("publication_id", "person_id", name="authorships_publication_person_uq"),
    Index(
        "idx_authorships_corresponding_uca",
        "publication_id",
        postgresql_where=text("(is_corresponding = true) AND (in_perimeter = true)"),
    ),
    Index(
        "idx_authorships_person",
        "person_id",
        postgresql_where=text("person_id IS NOT NULL"),
    ),
    Index("idx_authorships_pub", "publication_id"),
    Index(
        "idx_authorships_pub_uca",
        "publication_id",
        postgresql_where=text("in_perimeter = true"),
    ),
    Index(
        "idx_authorships_uca",
        "in_perimeter",
        postgresql_where=text("in_perimeter = true"),
    ),
)


# `authorship_structures` est une MATERIALIZED VIEW (DDL via migration
# a2c6e4f8b1d7), pas une table : dérivée des `source_authorship_structures` des
# `source_authorships` reliées à une authorship. Pas modélisée dans le metadata
# SQLAlchemy — tous les accès se font en SQL brut par nom (lectures) ou via
# REFRESH — pour éviter qu'`alembic --autogenerate` tente de la recréer en table.
#
# `publication_structures` (MATERIALIZED VIEW, migration d8b3f5a2c9e6) : lien
# publi↔structure dédoublonné, dérivé d'`authorships` × `authorship_structures`.
# Sert la facette labos (COUNT par structure sans DISTINCT). Même statut (SQL brut
# + REFRESH dans le pipeline, après `authorship_structures`).


rejected_authorships = Table(
    "rejected_authorships",
    metadata,
    Column("publication_id", Integer, nullable=False),
    Column("person_id", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    PrimaryKeyConstraint("publication_id", "person_id", name="rejected_authorships_pkey"),
)


# Identités d'auteur dédupliquées : la clé `(author_name_normalized,
# person_identifiers)` est extraite des signatures `source_authorships` (une
# identité pour ~25 signatures). L'unique est `NULLS NOT DISTINCT` : les
# signatures sans identifiant collapsent sur leur seul nom normalisé, sans
# recourir à un sentinel `'{}'`.
author_identifying_keys = Table(
    "author_identifying_keys",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("author_name_normalized", Text),
    Column("person_identifiers", JSONB),
    # Hash de la clé d'identité, chemin de lookup indexé et NULL-safe (un `=` ne
    # matche pas les NULL, un `IS NOT DISTINCT FROM` n'est pas indexable). Les
    # sentinelles E'\x01' (NULL) et E'\x1f' (séparateur) sont impossibles dans un
    # nom normalisé ou un jsonb::text. Respecte le NULLS NOT DISTINCT de l'unique.
    Column(
        "key_hash",
        Text,
        Computed(
            r"md5(coalesce(author_name_normalized, E'\x01') || E'\x1f' "
            r"|| coalesce(person_identifiers::text, E'\x01'))",
            persisted=True,
        ),
    ),
    UniqueConstraint(
        "author_name_normalized",
        "person_identifiers",
        name="author_identifying_keys_key",
        postgresql_nulls_not_distinct=True,
    ),
    Index("author_identifying_keys_key_hash_idx", "key_hash"),
)


source_authorships = Table(
    "source_authorships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", source_type_enum, nullable=False),
    Column("source_publication_id", Integer, nullable=False),
    Column("author_position", SmallInteger),
    Column("in_perimeter", Boolean, server_default="false"),
    Column("countries", ARRAY(Text)),
    # Refresh pays incrémental : True = `countries` à (re)calculer depuis les
    # adresses. Posé par normalize (nouveaux sa) et detect/institution (adresse
    # changée), remis à False par le refresh.
    Column("countries_dirty", Boolean, nullable=False, server_default="true"),
    Column("person_id", Integer),
    Column("is_corresponding", Boolean, server_default="false"),
    Column("roles", ARRAY(Text), server_default="{author}"),
    Column("authorship_id", Integer),
    Column("raw_author_name", Text),
    # FK vers `author_identifying_keys` (identité dédupliquée : nom normalisé +
    # identifiants observés de la signature). La contrainte FK n'est pas
    # modélisée ici (pattern du projet : les FK vivent en DB, pas dans la
    # MetaData).
    Column("identity_id", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint(
        "source_publication_id",
        "author_position",
        name="source_authorships_pub_pos_key",
    ),
    Index(
        "idx_sa_authorship",
        "authorship_id",
        postgresql_where=text("authorship_id IS NOT NULL"),
    ),
    Index(
        "idx_sa_in_perimeter",
        "source_publication_id",
        postgresql_where=text("in_perimeter = TRUE"),
    ),
    # Index couvrant : `person_id` en tête sert les recherches par personne ;
    # `identity_id` en colonne incluse permet l'index-only scan de la projection
    # `(person_id, identifiants)` de la file « conflits d'identifiant » (admin),
    # qui rejoint `author_identifying_keys` sur `identity_id`.
    Index(
        "idx_sa_person",
        "person_id",
        "identity_id",
        postgresql_where=text("person_id IS NOT NULL"),
    ),
    Index("idx_sa_identity", "identity_id"),
)


source_authorship_addresses = Table(
    "source_authorship_addresses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source_authorship_id", Integer, nullable=False),
    Column("address_id", Integer, nullable=False),
    UniqueConstraint(
        "source_authorship_id",
        "address_id",
        name="source_authorship_addresses_source_authorship_id_address_id_key",
    ),
    Index("idx_saa_address", "address_id"),
)


# `source_authorship_structures` est une MATERIALIZED VIEW (DDL via migration
# e8f1a3c5d7b9), pas une table : dérivée de `source_authorship_addresses ⋈
# address_structures ⋈ perimeter_structures` (périmètre d'affiliation). Non
# modélisée dans le metadata SQLAlchemy — accès en SQL brut par nom (lectures)
# ou via REFRESH — pour éviter qu'`alembic --autogenerate` tente de la recréer
# en table.


# ── Personnes ─────────────────────────────────────────────────────


persons = Table(
    "persons",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("last_name", Text, nullable=False),
    Column("first_name", Text, nullable=False),
    Column("last_name_normalized", Text, nullable=False),
    Column("first_name_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("rejected", Boolean, server_default="false"),
    Index("idx_persons_name", "last_name_normalized", "first_name_normalized"),
)


persons_rh = Table(
    "persons_rh",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("person_id", Integer, nullable=False),
    Column("email", Text),
    Column("role_title", Text),
    Column("department_name", Text),
    Column("structure_id", Integer),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("hr_export_date", Date),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("person_id", name="persons_rh_person_id_key"),
    Index("idx_persons_rh_department", "department_name"),
    Index("idx_persons_rh_person_id", "person_id"),
)


person_identifiers = Table(
    "person_identifiers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("person_id", Integer, nullable=False),
    Column("id_type", Text, nullable=False),
    Column("id_value", Text, nullable=False),
    Column("source", identifier_origin_enum, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("status", identifier_status_enum, nullable=False, server_default="pending"),
    UniqueConstraint("id_type", "id_value", name="person_identifiers_id_type_id_value_key"),
    Index("idx_person_ids_lookup", "id_type", "id_value"),
    Index("idx_person_ids_person", "person_id"),
)


person_name_forms = Table(
    "person_name_forms",
    metadata,
    Column("name_form", Text, nullable=False),
    Column("person_id", Integer, nullable=False),
    Column("sources", ARRAY(Text), nullable=False, server_default="{}"),
    Column("status", identifier_status_enum, nullable=False, server_default="pending"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    PrimaryKeyConstraint("name_form", "person_id", name="person_name_forms_pkey"),
    Index("idx_pnf_person_id", "person_id"),
)


# ── Publications ──────────────────────────────────────────────────


publications = Table(
    "publications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text),
    Column("doc_type", doc_type_enum, server_default="other"),
    Column("pub_year", SmallInteger, nullable=False),
    Column("doi", Text),
    Column("oa_status", oa_type_enum, server_default="unknown"),
    Column("journal_id", Integer),
    Column("container_title", Text),
    Column("language", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("countries", ARRAY(Text)),
    Column("sources", ARRAY(source_type_enum), nullable=False, server_default="{}"),
    Column("meta", JSONB),
    Column("is_retracted", Boolean, nullable=False, server_default="false"),
    # abstract / keywords / topics / biblio sont dans `publications_detail` (1:1) :
    # colonnes grasses lues uniquement par la page détail, sorties pour garder
    # `publications` étroite (scans listes/facettes).
    # Flag périmètre matérialisé (rollup de authorships.in_perimeter, hors personnes
    # rejetées), maintenu en phase authorships + à l'action de rejet. Lu par le filtre
    # des listes UCA (cf. publication_in_perimeter) ; le scope doc_type reste un filtre
    # inline (domain/publications/scope), séparé du périmètre.
    Column("in_perimeter", Boolean, nullable=False, server_default="false"),
    # Staleness de l'enrichissement OA : date de la dernière vérification Unpaywall
    # (NULL = jamais). La phase oa_status ne re-vérifie que les non-vérifiés ou les
    # statuts changeables périmés (cf. STABLE_OA_STATUSES, application/.../oa_status).
    Column("unpaywall_checked_at", DateTime(timezone=True)),
    Index(
        "idx_pub_countries",
        "countries",
        postgresql_using="gin",
        postgresql_where=text("countries IS NOT NULL"),
    ),
    Index(
        "idx_pub_title_trgm",
        "title_normalized",
        postgresql_ops={"title_normalized": "gin_trgm_ops"},
        postgresql_using="gin",
    ),
    Index("idx_publications_journal", "journal_id"),
    Index(
        "idx_publications_meta",
        "meta",
        postgresql_using="gin",
        postgresql_where=text("meta IS NOT NULL"),
    ),
    Index("idx_publications_sources", "sources", postgresql_using="gin"),
    Index("idx_publications_titlenorm_year", "title_normalized", "pub_year"),
    Index("idx_publications_year", "pub_year"),
    Index("idx_publications_year_type", "pub_year", "doc_type"),
    # Listes scopées au périmètre : tri par défaut (pub_year DESC) et sous-requêtes
    # pub_count par éditeur/revue (jointure via journal_id), restreints au périmètre.
    Index(
        "idx_publications_in_perimeter_year",
        text("pub_year DESC"),
        postgresql_where=text("in_perimeter"),
    ),
    Index(
        "idx_publications_in_perimeter_journal",
        "journal_id",
        postgresql_where=text("in_perimeter"),
    ),
    # Index UNIQUE sur expression lower(doi) — complété à la main. L'unicité
    # « 1 DOI = 1 publication » est garantie par la DB : la réconciliation des
    # composantes ne produit jamais deux publications au même DOI (assignation à
    # l'unique pub-ancre de la partition `(composante ∩ DOI)`). Partiel : les
    # publications sans DOI (NULL) ne sont pas contraintes.
    Index(
        "publications_doi_lower_key",
        text("lower(doi)"),
        unique=True,
        postgresql_where=text("doi IS NOT NULL"),
    ),
    # Fetch incrémental oa_status : jamais vérifiés (NULL) d'abord, puis les plus périmés.
    Index(
        "idx_pub_unpaywall_checked",
        text("unpaywall_checked_at NULLS FIRST"),
        postgresql_where=text("doi IS NOT NULL"),
    ),
)


# Colonnes grasses detail-only sorties de `publications` (1:1, FK ON DELETE CASCADE
# côté schéma — voir migration). Lues par la page détail et `find_by_id`, écrites
# par `publication_repository.save` (upsert).
publications_detail = Table(
    "publications_detail",
    metadata,
    Column("publication_id", Integer, primary_key=True),
    Column("abstract", Text),
    Column("keywords", ARRAY(Text)),
    Column("topics", JSONB),
    Column("biblio", JSONB),
)


source_publications = Table(
    "source_publications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", source_type_enum, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("doi", Text),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text),
    Column("pub_year", SmallInteger),
    Column("doc_type", Text),
    Column("publication_id", Integer),
    Column("staging_id", Integer),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column(
        "updated_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=text("clock_timestamp()"),
    ),
    Column("countries", ARRAY(Text)),
    Column("hal_collections", ARRAY(Text)),
    Column(
        "external_ids",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("urls", ARRAY(Text)),
    Column("cited_by_count", Integer),
    Column("journal_id", Integer),
    Column("oa_status", Text),
    Column("embargo_until", Date),
    Column("language", Text),
    Column("container_title", Text),
    Column("is_retracted", Boolean),
    Column("abstract", Text),
    Column("keywords", ARRAY(Text)),
    Column("topics", JSONB),
    Column("biblio", JSONB),
    Column("meta", JSONB),
    Column(
        "raw_metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("keys_dirty", Boolean, nullable=False, server_default="true"),
    UniqueConstraint("source", "source_id", name="source_publications_source_source_id_key"),
    Index(
        "idx_source_pubs_title_normalized_trgm",
        "title_normalized",
        postgresql_using="gin",
        postgresql_ops={"title_normalized": "gin_trgm_ops"},
    ),
    Index(
        "idx_source_pubs_countries",
        "countries",
        postgresql_using="gin",
        postgresql_where=text("countries IS NOT NULL"),
    ),
    Index("idx_source_pubs_doi", "doi", postgresql_where=text("doi IS NOT NULL")),
    Index(
        "idx_source_pubs_external_ids",
        "external_ids",
        postgresql_using="gin",
        postgresql_where=text("external_ids != '{}'::jsonb"),
    ),
    CheckConstraint(
        "jsonb_typeof(external_ids) = 'object'",
        name="source_publications_external_ids_is_object",
    ),
    CheckConstraint(
        "jsonb_typeof(raw_metadata) = 'object'",
        name="source_publications_raw_metadata_is_object",
    ),
    Index(
        "idx_source_pubs_hal_collections",
        "hal_collections",
        postgresql_using="gin",
        postgresql_where=text("hal_collections IS NOT NULL"),
    ),
    Index(
        "idx_source_pubs_pub",
        "publication_id",
        postgresql_where=text("publication_id IS NOT NULL"),
    ),
    Index(
        "idx_source_pubs_keys_dirty",
        "keys_dirty",
        postgresql_where=text("keys_dirty"),
    ),
    Index(
        "idx_source_pubs_staging",
        "staging_id",
        postgresql_where=text("staging_id IS NOT NULL"),
    ),
)


distinct_persons = Table(
    "distinct_persons",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("person_id_a", Integer, nullable=False),
    Column("person_id_b", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint("person_id_a < person_id_b", name="distinct_persons_ordered"),
    UniqueConstraint(
        "person_id_a",
        "person_id_b",
        name="distinct_persons_person_id_a_person_id_b_key",
    ),
)


distinct_publications = Table(
    "distinct_publications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("pub_id_a", Integer, nullable=False),
    Column("pub_id_b", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    CheckConstraint("pub_id_a < pub_id_b", name="distinct_pubs_ordered"),
    UniqueConstraint(
        "pub_id_a",
        "pub_id_b",
        name="distinct_publications_pub_id_a_pub_id_b_key",
    ),
    Index("idx_distinct_pubs_a", "pub_id_a"),
    Index("idx_distinct_pubs_b", "pub_id_b"),
)


apc_payments = Table(
    "apc_payments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("lab_name", Text),
    Column("publisher_name", Text),
    Column("publisher_type", Text),
    Column("journal_name", Text),
    Column("issn", Text),
    Column("journal_type", Text),
    Column("doi", Text),
    Column("article_title", Text),
    Column("amount_eur_ht", Numeric(12, 2)),
    Column("billing_year", SmallInteger),
    Column("pub_year", SmallInteger),
    Column("budget", Text),
    Column("institution", Text),
    Column("institution_type", Text),
    Column("coman_id", Integer),
    Column("all_surveys_answered", Text),
    Column("shared_payment", Text),
    Column("source_file", Text),
    Column("expense_type", Text),
    Column("remarks", Text),
    Column("publication_id", Integer),
    Column("journal_id", Integer),
    Column("publisher_id", Integer),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("budget_structure_id", Integer),
    Column("lab_structure_id", Integer),
    Index("idx_apc_billing_year", "billing_year"),
    Index(
        "idx_apc_budget_struct",
        "budget_structure_id",
        postgresql_where=text("budget_structure_id IS NOT NULL"),
    ),
    # Index sur expression lower(doi) — complété à la main.
    Index("idx_apc_doi", text("lower(doi)"), postgresql_where=text("doi IS NOT NULL")),
    Index("idx_apc_institution", "institution"),
    Index(
        "idx_apc_lab_struct",
        "lab_structure_id",
        postgresql_where=text("lab_structure_id IS NOT NULL"),
    ),
    Index(
        "idx_apc_pub",
        "publication_id",
        postgresql_where=text("publication_id IS NOT NULL"),
    ),
)


countries = Table(
    "countries",
    metadata,
    Column("code", CHAR(2), primary_key=True),
    Column("name", Text, nullable=False),
)


staging = Table(
    "staging",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", source_type_enum, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("doi", Text),
    Column("raw_data", JSONB, nullable=False),
    Column("processed", Boolean, server_default="false"),
    Column("imported_at", DateTime(timezone=True), server_default=func.now()),
    Column(
        "raw_hash",
        Text,
        comment=(
            "Empreinte md5 du payload tel qu'extrait de la source bulk. "
            "Sert de clé de détection de changement à l'UPSERT (et "
            "d'empreinte d'intégrité pour le chantier DATA_raw-data-store). "
            "Cas particulier OpenAlex : `refetch_truncated` n'écrit PAS "
            "`raw_hash` quand il complète les authorships d'une publication "
            "tronquée à 100 — la ligne garde le hash du payload bulk pour "
            "que le bulk suivant ne déclenche pas de réécriture inutile. "
            "L'invariant `raw_hash = md5(raw_data)` est donc volontairement "
            "rompu sur les lignes OpenAlex refetchées."
        ),
    ),
    Column("last_seen_at", DateTime(timezone=True), server_default=func.now()),
    Column("not_found_at", DateTime(timezone=True)),
    Column("disappeared_at", DateTime(timezone=True)),
    # OpenAlex : payload bulk plafonné à 100 auteurs → work probablement tronqué.
    # Posé à l'extraction, consommé puis effacé par `refetch_truncated`.
    Column("authors_truncated", Boolean, nullable=False, server_default="false"),
    # Provenance d'entrée : 'bulk' (extraction) ou 'cross_import_doi' / 'cross_import_hal'.
    Column("entry_mode", Text, nullable=False, server_default="bulk"),
    UniqueConstraint("source", "source_id", name="staging_source_source_id_key"),
    CheckConstraint(
        "not_found_at IS NULL OR processed",
        name="staging_not_found_at_implies_processed",
    ),
    Index("idx_staging_doi", "doi", postgresql_where=text("doi IS NOT NULL")),
    Index("idx_staging_processed", "processed", postgresql_where=text("NOT processed")),
    Index("idx_staging_source", "source"),
)


# Cache des tentatives négatives de cross-import DOI sur les sources non
# natives (hal, openalex, wos, scanr) : un DOI absent d'une de ces sources
# n'y est pas définitivement absent, on le re-tente après `next_retry`. Tient
# le pool `get_cross_import_dois` auto-borné. Distinct de `staging` : ce ne
# sont pas des documents (pas de payload, pas de cycle de normalisation).
doi_lookups = Table(
    "doi_lookups",
    metadata,
    Column("source", source_type_enum, nullable=False),
    Column("doi", Text, nullable=False),
    Column("not_found_at", DateTime(timezone=True), nullable=False),
    Column("next_retry", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("source", "doi"),
)


subjects = Table(
    "subjects",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("label", Text, nullable=False),
    Column("language", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("usage_count", Integer, nullable=False, server_default="0"),
    Column("ontologies", JSONB, nullable=False, server_default="{}"),
    # Index UNIQUE sur expression lower(label) — complété à la main.
    Index("subjects_label_key", text("lower(label)"), unique=True),
    # Index GIN trigram sur expression normalize_name_form(label) — complété
    # à la main (sqlacodegen ne sait pas représenter cette expression).
    # L'op `gin_trgm_ops` est passé via postgresql_ops pour permettre la
    # comparaison fine de l'expression par Alembic. Pas de préfixe `public.`
    # ici : la reflection Postgres ne le renvoie pas, donc le préfixe
    # générerait un diff cosmétique permanent.
    Index(
        "subjects_label_norm_trgm_idx",
        text("normalize_name_form(label)"),
        postgresql_ops={"normalize_name_form(label)": "gin_trgm_ops"},
        postgresql_using="gin",
    ),
    Index("subjects_usage_count_idx", text("usage_count DESC")),
)


publication_subjects = Table(
    "publication_subjects",
    metadata,
    Column("publication_id", Integer, nullable=False),
    Column("subject_id", Integer, nullable=False),
    Column("source", source_type_enum, nullable=False),
    Column("score", REAL),
    Column("rejected", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    PrimaryKeyConstraint("publication_id", "subject_id", "source"),
    Index("publication_subjects_subject_idx", "subject_id"),
)


# `subject_cooccurrences` est une MATERIALIZED VIEW (alembic
# `c8a3f2e5b4d7`). La projection SA Core ci-dessous sert uniquement aux
# SELECT côté queries — les contraintes/indexes vivent en migration.
subject_cooccurrences = Table(
    "subject_cooccurrences",
    metadata,
    Column("subject_a_id", Integer, nullable=False),
    Column("subject_b_id", Integer, nullable=False),
    Column("count", Integer, nullable=False),
    PrimaryKeyConstraint("subject_a_id", "subject_b_id"),
    info={"is_view": True},
)
