"""Modèle SQLAlchemy des tables Postgres — surface de query-building.

Décrit tables, colonnes, contraintes uniques, CHECK et comments, pour deux usages :
- le query-building côté SQLAlchemy Core (`select(config.c.key)…`),
- servir de référence à `alembic revision --autogenerate` (comparaison MetaData ↔ DB).

Ce modèle n'est pas la source de vérité du schéma : les migrations Alembic (`alembic/versions/`, écrites à la main) font foi, et `infrastructure/db/schema.sql` en est un snapshot descriptif régénéré par `python -m infrastructure.db.dump_schema`. Le fichier est maintenu à la main en miroir de la base ; le test `tests/integration/infrastructure/db/test_sqlalchemy_smoke.py` garde les deux cohérents, en vérifiant que colonnes déclarées et colonnes réelles coïncident.

Le périmètre du metadata s'arrête aux tables et à leurs colonnes. Index, clés étrangères et vues matérialisées (`authorship_structures`, `publication_structures`, `source_authorship_structures`, `subject_cooccurrences`) appartiennent aux seules migrations ; le filtre `include_object` d'`alembic/env.py` les écarte de la comparaison.
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
from sqlalchemy.dialects.postgresql import ARRAY, ENUM as PgEnum, JSONB

from domain.sources.registry import ALL_SOURCES

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

oa_model_enum = PgEnum(
    "subscription",
    "full_oa",
    "repository",
    name="oa_model",
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
    Column("apc_amount", Numeric(10, 2)),
    Column("apc_currency", Text, server_default="EUR"),
    Column("oa_model", oa_model_enum),
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
)


publishers = Table(
    "publishers",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_normalized", Text, nullable=False),
    Column("openalex_id", Text),
    Column("country", Text),
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
)


publisher_name_forms = Table(
    "publisher_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("publisher_id", Integer, nullable=False),
    Column("form_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("form_normalized", name="publisher_name_forms_form_normalized_key"),
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

# Valeurs dérivées du registre : l'enum Postgres est créé par migration
# (`create_type=False`), et `TestSourcesEnum` compare le registre à la base.
source_type_enum = PgEnum(*ALL_SOURCES, name="source_type", create_type=False)

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

resolution_mode_enum = PgEnum(
    "identifier",
    "name",
    "cross_source",
    name="resolution_mode",
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
    # Refresh pays incrémental : True = `countries` vient de changer, les
    # `source_authorships` liés sont à recalculer. Posé gratuitement à l'écriture
    # de `countries` (detect / institution), dérivé par JOIN au refresh, purgé en
    # fin de cascade.
    Column("countries_dirty", Boolean, nullable=False, server_default="false"),
    # Index UNIQUE sur expression md5(raw_text) — complété à la main, hors
    # de portée de --autogenerate qui ne sait pas représenter l'expression.
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
    # cas d'usage principal (résolution d'un nom de pays vers son code ISO).
    Column("kind", Text, nullable=False, server_default="country"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("form_normalized", name="place_name_forms_form_normalized_key"),
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
)


# `authorship_structures` est une MATERIALIZED VIEW (DDL via migration
# a2c6e4f8b1d7), pas une table : dérivée des `source_authorship_structures` des
# `source_authorships` reliées à une authorship. Pas modélisée dans le metadata
# SQLAlchemy — tous les accès se font en SQL brut par nom (lectures) ou via
# REFRESH — pour éviter qu'`alembic --autogenerate` tente de la recréer en table.
#
# `publication_structures` (MATERIALIZED VIEW, migration d8b3f5a2c9e6) : lien
# publication↔structure dédoublonné, dérivé d'`authorships` × `authorship_structures`.
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
)


source_authorships = Table(
    "source_authorships",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", source_type_enum, nullable=False),
    Column("source_publication_id", Integer, nullable=False),
    Column("author_position", SmallInteger),
    Column("in_perimeter", Boolean, server_default="false"),
    # Refresh pays incrémental : True = les pays dérivés (source_publications,
    # publications) sont à recalculer depuis les adresses de ce source_authorship.
    # Posé par normalize (nouveaux source_authorships) et la détection (adresse
    # changée), remis à False par le refresh.
    Column("countries_dirty", Boolean, nullable=False, server_default="true"),
    Column("person_id", Integer),
    # Canal ayant posé `person_id` (NULL si orpheline ou non résolue) : identifiant
    # fort, forme de nom, ou ancrage cross-source. Partitionne la ré-évaluation des
    # rattachements par la phase personnes.
    Column("resolution_mode", resolution_mode_enum),
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
    # Index couvrant : `person_id` en tête sert les recherches par personne ;
    # `identity_id` en colonne incluse permet l'index-only scan de la projection
    # `(person_id, identifiants)` de la file « conflits d'identifiant » (admin),
    # qui rejoint `author_identifying_keys` sur `identity_id`.
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
    # de périmètre des listes (cf. publication_in_perimeter) ; le scope doc_type reste
    # un filtre inline (domain/publications/scope), séparé du périmètre.
    Column("in_perimeter", Boolean, nullable=False, server_default="false"),
    # Staleness de l'enrichissement OA : date de la dernière interrogation d'Unpaywall
    # (NULL = jamais), qu'elle ait trouvé la publication ou non. La phase `oa_status`
    # re-vérifie les jamais-interrogées, puis les plus périmées.
    Column("unpaywall_checked_at", DateTime(timezone=True)),
    # Listes scopées au périmètre : tri par défaut (pub_year DESC) et sous-requêtes
    # pub_count par éditeur/revue (jointure via journal_id), restreints au périmètre.
    # Index UNIQUE sur expression lower(doi) — complété à la main. L'unicité
    # « 1 DOI = 1 publication » est garantie par la DB : la réconciliation des
    # composantes ne produit jamais deux publications au même DOI (assignation à
    # l'unique pub-ancre de la partition `(composante ∩ DOI)`). Partiel : les
    # publications sans DOI (NULL) ne sont pas contraintes.
    # Fetch incrémental oa_status : jamais vérifiés (NULL) d'abord, puis les plus périmés.
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
    CheckConstraint(
        "jsonb_typeof(external_ids) = 'object'",
        name="source_publications_external_ids_is_object",
    ),
    CheckConstraint(
        "jsonb_typeof(raw_metadata) = 'object'",
        name="source_publications_raw_metadata_is_object",
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
)


# Relevés de paiements de frais de publication (Article Processing Charges) :
# une ligne par paiement, importés depuis des exports comptables (colonnes à
# plat ; `source_file` trace le fichier d'origine). `publication_id`,
# `journal_id`, `publisher_id` et `*_structure_id` sont rapprochés après import.
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
    # Index sur expression lower(doi) — complété à la main.
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
            "Empreinte md5 servant de clé de détection de changement à l'UPSERT. "
            "Calculée via `change_detection_hash`, qui neutralise le bruit volatil "
            "propre à la source avant l'empreinte (HAL : horodatage de génération "
            "du TEI `label_xml`) — le payload stocké reste, lui, fidèle à la source. "
            "L'empreinte ne coïncide donc pas avec `md5(raw_data)` pour les sources "
            "normalisées. Cas particulier OpenAlex : `refetch_truncated` n'écrit PAS "
            "`raw_hash` quand il complète les authorships d'une publication tronquée "
            "à 100 — la ligne garde le hash du payload bulk pour que le bulk suivant "
            "ne déclenche pas de réécriture inutile."
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
)


# Cache des tentatives négatives de cross-import par DOI. `next_retry` NULL = miss
# définitif (crossref, datacite : le DOI est leur identifiant natif, un 404 est sans
# appel) ; `next_retry` daté = miss transitoire d'une source non native (hal, openalex,
# wos, scanr), re-tenté après le délai. Tient le pool `get_cross_import_dois` auto-borné.
# Distinct de `staging` : ce ne sont pas des documents (pas de payload, pas de cycle de
# normalisation).
doi_lookups = Table(
    "doi_lookups",
    metadata,
    Column("source", source_type_enum, nullable=False),
    Column("doi", Text, nullable=False),
    Column("not_found_at", DateTime(timezone=True), nullable=False),
    Column("next_retry", DateTime(timezone=True), nullable=True),
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
    # Index UNIQUE sur expression lower(label) — complété à la main.
    # Index GIN trigram sur expression normalize_name_form(label) — complété
    # à la main (sqlacodegen ne sait pas représenter cette expression).
    # L'op `gin_trgm_ops` est passé via postgresql_ops pour permettre la
    # comparaison fine de l'expression par Alembic. Pas de préfixe `public.`
    # ici : la reflection Postgres ne le renvoie pas, donc le préfixe
    # générerait un diff cosmétique permanent.
)


publication_subjects = Table(
    "publication_subjects",
    metadata,
    Column("publication_id", Integer, nullable=False),
    Column("subject_id", Integer, nullable=False),
    Column("source", source_type_enum, nullable=False),
    Column("rejected", Boolean, nullable=False, server_default="false"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    PrimaryKeyConstraint("publication_id", "subject_id", "source"),
)


# `subject_cooccurrences` est une MATERIALIZED VIEW (migration c8a3f2e5b4d7),
# pas une table : paires de sujets co-présents sur une même publication, avec
# leur effectif (seuil `count >= 2`). Non modélisée dans le metadata SQLAlchemy
# — accès en SQL brut par nom (lectures) ou via REFRESH — pour éviter
# qu'`alembic --autogenerate` tente de la recréer en table.
