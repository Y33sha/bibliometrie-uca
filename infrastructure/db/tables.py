"""Modèle SQLAlchemy des tables Postgres — surface de query-building.

Décrit tables, colonnes, contraintes uniques, CHECK et comments, pour deux usages :
- le query-building côté SQLAlchemy Core (`select(config.c.key)…`),
- servir de référence à `alembic revision --autogenerate` (comparaison MetaData ↔ DB).

Ce modèle n'est pas la source de vérité du schéma : les migrations Alembic (`alembic/versions/`, écrites à la main) font foi, et `infrastructure/db/schema.sql` en est un snapshot descriptif régénéré par `python -m interfaces.cli.dev.dump_schema`. Le fichier est maintenu à la main en miroir de la base ; `alembic check`, joué par `tests/integration/infrastructure/db/test_sqlalchemy_smoke.py` sur une base montée par les migrations, tient l'accord entre les deux.

Le périmètre du metadata s'arrête aux tables et à leurs colonnes. Index, clés étrangères et vues matérialisées (`contribution_structures`, `publication_author_alignment`, `publication_rors`, `publication_structures`, `source_contribution_structures`, `subject_cooccurrences`) appartiennent aux seules migrations ; le filtre `include_object` d'`alembic/env.py` les écarte de la comparaison.
"""

from sqlalchemy import (
    CHAR,
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Computed,
    Date,
    DateTime,
    Float,
    Identity,
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
from sqlalchemy.dialects.postgresql import ARRAY, ENUM as PgEnum

from domain.config import CAP_KEYS, DELAY_KEYS, MAX_YEAR, MIN_YEAR, YEAR_KEYS
from domain.countries import PlaceNameKind
from domain.country_detection import CountryDetectionMethod
from domain.merge import MergedEntity
from domain.persons.group_matching import GroupMatchReason
from domain.persons.identifiers import AttributionStatus
from domain.persons.person import PersonExclusion
from domain.platforms.platform import PLATFORM_TYPES
from domain.publications.author_grouping import GroupingMethod
from domain.publications.doc_types import DOC_TYPES
from domain.publications.licenses import License
from domain.publications.metadata import OA_RANK
from domain.publications.relations import RelationType
from domain.publishers.publisher import PUBLISHER_TYPES
from domain.serials.issns import ISSN_STATUSES, ISSN_SUPPORTS
from domain.serials.serial import OA_MODELS, SERIAL_TYPES
from domain.sources.registry import ALL_SOURCES, LOOKUP_SOURCES
from domain.sources.staging import StagingEntryMode
from domain.structures.hal_structures import HalStructureStatus
from domain.structures.perimeter_evidence import PerimeterEvidence
from domain.structures.ror import RorStatus, RorType
from domain.structures.structure import StructureType
from infrastructure.db.jsonb import Jsonb

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
            "Type de l'entité affectée : address, journal, perimeter, person, publication, structure."
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
        Jsonb,
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
    schema="ops",
)


config = Table(
    "config",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", Jsonb, nullable=False),
    Column("description", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    # `value` est jsonb : la forme attendue dépend de la clé, que le domaine énumère.
    CheckConstraint(
        f"key NOT IN ({', '.join(repr(key) for key in sorted(CAP_KEYS))}) "
        "OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 0 "
        "AND (value)::numeric = trunc((value)::numeric))",
        name="config_cap_is_non_negative_integer",
    ),
    CheckConstraint(
        f"key NOT IN ({', '.join(repr(key) for key in sorted(YEAR_KEYS))}) "
        f"OR (jsonb_typeof(value) = 'number' "
        f"AND (value)::numeric BETWEEN {MIN_YEAR} AND {MAX_YEAR} "
        "AND (value)::numeric = trunc((value)::numeric))",
        name="config_year_is_in_range",
    ),
    CheckConstraint(
        f"key NOT IN ({', '.join(repr(key) for key in sorted(DELAY_KEYS))}) "
        "OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 1 "
        "AND (value)::numeric = trunc((value)::numeric))",
        name="config_delay_is_positive_integer",
    ),
    schema="ops",
)


users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "login",
        Text,
        nullable=False,
        comment=(
            "Identifiant de connexion : identifiant CAS, ou ADMIN_USER pour la connexion "
            "par mot de passe."
        ),
    ),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    UniqueConstraint("login", name="users_login_key"),
    comment="Utilisateurs autorisés à ouvrir une session.",
    schema="ops",
)


roles = Table(
    "roles",
    metadata,
    Column("code", Text, primary_key=True),
    Column("label", Text, nullable=False),
    comment="Rôles que le code connaît (domain.users.Role).",
    schema="ops",
)


user_roles = Table(
    "user_roles",
    metadata,
    Column("user_id", Integer, nullable=False),
    Column("role_code", Text, nullable=False),
    PrimaryKeyConstraint("user_id", "role_code", name="user_roles_pkey"),
    comment="Rôles attribués à chaque utilisateur.",
    schema="ops",
)


merge_redirects = Table(
    "merge_redirects",
    metadata,
    Column(
        "entity",
        PgEnum(*MergedEntity, name="merged_entity", create_type=False),
        primary_key=True,
    ),
    Column("absorbed_id", Integer, primary_key=True),
    Column("kept_id", Integer, nullable=False),
    Column("merged_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    comment=(
        "Identifiant d'une entité absorbée par une fusion, et identifiant de l'entité conservée. "
        "Une redirection en chaîne mène directement à la dernière entité conservée."
    ),
)


perimeters = Table(
    "perimeters",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("code", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column(
        "root_structure_ids",
        ARRAY(Integer),
        nullable=False,
        server_default=text("'{}'::integer[]"),
    ),
    UniqueConstraint("code", name="perimeters_code_key"),
    schema="structures",
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
    schema="structures",
)


# Les enums Postgres déclarent leur type côté SA pour que les binds produisent un cast typé — un
# paramètre VARCHAR ne rejoint pas une enum — et pour que la lecture reconnaisse la valeur reçue.
# Leur vocabulaire vient du domaine, qui le déclare ; `create_type=False` laisse les migrations
# créer le type. `TestPgEnumsMatchDb` vérifie l'accord des trois.
structure_type_enum = PgEnum(
    *(t.value for t in StructureType),
    name="structure_type",
    create_type=False,
)

publisher_type_enum = PgEnum(*PUBLISHER_TYPES, name="publisher_type", create_type=False)

person_exclusion_enum = PgEnum(
    *(e.value for e in PersonExclusion),
    name="person_exclusion",
    create_type=False,
)

serial_type_enum = PgEnum(*SERIAL_TYPES, name="serial_type", create_type=False)

oa_model_enum = PgEnum(*OA_MODELS, name="oa_model", create_type=False)
issn_support_enum = PgEnum(*ISSN_SUPPORTS, name="issn_support", create_type=False)
issn_status_enum = PgEnum(*ISSN_STATUSES, name="issn_status", create_type=False)


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
    Column("api_ids", Jsonb),
    UniqueConstraint("code", name="structures_code_key"),
    UniqueConstraint("ror_id", name="structures_ror_id_key"),
    schema="structures",
)


structure_parents = Table(
    "structure_parents",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("parent_id", Integer, nullable=False),
    Column("child_id", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint(
        "parent_id",
        "child_id",
        name="structure_parents_parent_id_child_id_key",
    ),
    CheckConstraint("parent_id <> child_id", name="structure_parents_no_self_reference"),
    schema="structures",
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
    # Une forme courte ne s'apparie qu'aux frontières de mot : sans cela, un acronyme de
    # quelques lettres se retrouverait au milieu de n'importe quel mot d'une adresse.
    CheckConstraint(
        "char_length(form_text) > 6 OR is_word_boundary",
        name="ck_structure_name_forms_short_word_boundary",
    ),
    schema="structures",
)


ror_status_enum = PgEnum(*(s.value for s in RorStatus), name="ror_status", create_type=False)
ror_type_enum = PgEnum(*(t.value for t in RorType), name="ror_type", create_type=False)

ror_organizations = Table(
    "ror_organizations",
    metadata,
    Column("ror_id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("country_code", CHAR(2), nullable=False),
    Column("types", ARRAY(ror_type_enum), nullable=False),
    Column("status", ror_status_enum, nullable=False),
    comment=(
        "Organisations du Research Organization Registry, chargées depuis son dump. "
        "Référentiel externe en lecture seule : structures.ror_id le relie au référentiel interne."
    ),
    schema="ref",
)


ror_relations = Table(
    "ror_relations",
    metadata,
    Column("parent_ror_id", Text, nullable=False),
    Column("child_ror_id", Text, nullable=False),
    PrimaryKeyConstraint("parent_ror_id", "child_ror_id", name="ror_relations_pkey"),
    CheckConstraint("parent_ror_id <> child_ror_id", name="ror_relations_no_self_reference"),
    comment="Relations parent/enfant entre organisations du Research Organization Registry.",
    schema="ref",
)


hal_structure_status_enum = PgEnum(
    *(s.value for s in HalStructureStatus), name="hal_structure_status", create_type=False
)

hal_structures = Table(
    "hal_structures",
    metadata,
    Column("hal_structure_id", Integer, primary_key=True, autoincrement=False),
    Column("name", Text, nullable=False),
    Column("acronym", Text),
    Column("structure_type", Text, nullable=False),
    Column("country_code", CHAR(2)),
    Column("status", hal_structure_status_enum, nullable=False),
    Column("ror_id", Text),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("parent_ids", ARRAY(Integer), nullable=False, server_default="{}"),
    Column("fetched_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Structure interne, quand le ROR ne relie pas la structure HAL au référentiel interne.
    Column("structure_id", Integer),
    comment=(
        "Structures du référentiel HAL (ref/structure). Référentiel externe : son ROR, ou "
        "structure_id, le relie au référentiel interne."
    ),
    schema="ref",
)


hal_structure_relations = Table(
    "hal_structure_relations",
    metadata,
    Column("parent_id", Integer, nullable=False),
    Column("child_id", Integer, nullable=False),
    PrimaryKeyConstraint("parent_id", "child_id", name="hal_structure_relations_pkey"),
    CheckConstraint("parent_id <> child_id", name="hal_structure_relations_no_self_reference"),
    comment="Relations parent/enfant entre structures du référentiel HAL.",
    schema="ref",
)


hal_structure_aliases = Table(
    "hal_structure_aliases",
    metadata,
    Column("alias_id", Integer, primary_key=True, autoincrement=False),
    Column("hal_structure_id", Integer, nullable=False),
    comment="Fiches en double du référentiel HAL, fondues dans une structure conservée.",
    schema="ref",
)


ror_dump_imports = Table(
    "ror_dump_imports",
    metadata,
    Column("version", Text, primary_key=True),
    Column("imported_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    comment="Imports du dump ROR : nom de l'archive importée et date de l'import.",
    schema="ref",
)


serials = Table(
    "serials",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text, nullable=False),
    Column("publisher_id", Integer),
    Column("openalex_id", Text),
    Column("is_in_doaj", Boolean, server_default="false"),
    Column("apc_amount", Numeric(10, 2)),
    Column("apc_currency", Text, server_default="EUR"),
    Column("oa_model", oa_model_enum),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("serial_type", serial_type_enum, server_default="unknown"),
    Column("is_academic", Boolean, server_default="true"),
    Column("doaj_payload", Jsonb),
    Column("doaj_imported_at", DateTime(timezone=True)),
    # Compte matérialisé des publications in-perimeter de la revue. Maintenu par le
    # pipeline (après le rollup in_perimeter) + aux fusions admin. Évite de re-scanner
    # publications pour le filtre `with_publications` / le tri / l'affichage.
    Column("publication_count", Integer, nullable=False, server_default="0"),
    # Champs saisis à la main (`domain.serials.journal.ManualField`) : le pipeline ne les écrit pas.
    Column("manual_fields", ARRAY(Text), nullable=False, server_default="{}"),
    UniqueConstraint("openalex_id", name="serials_openalex_id_key"),
    schema="publishing",
)


serial_issns = Table(
    "serial_issns",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "issn",
        Text,
        nullable=False,
        comment="Forme normalisée si la valeur est valide, valeur reçue sinon (statut malformed).",
    ),
    Column("serial_id", Integer),
    Column("support", issn_support_enum, comment="Support de l'ISSN. NULL : inconnu."),
    Column(
        "linking",
        Boolean,
        nullable=False,
        server_default="false",
        comment="Vrai pour l'ISSN-L de la revue.",
    ),
    Column(
        "status",
        issn_status_enum,
        nullable=False,
        server_default="active",
        comment=(
            "active ; malformed (forme ou clé de contrôle fausse) ; cancelled ; related_title (titre "
            "précédent ou suivant) ; supplement ; unverified (valeur mise de côté, motif inconnu)."
        ),
    ),
    Column(
        "replaced_by",
        Text,
        comment="ISSN successeur : titre suivant, forme corrigée d'une valeur mal formée.",
    ),
    Column(
        "sudoc_checked_at",
        DateTime(timezone=True),
        comment="Date de la vérification de l'ISSN au Sudoc. NULL : jamais vérifié.",
    ),
    UniqueConstraint(
        "issn",
        "serial_id",
        name="uq_serial_issns_issn_serial",
        postgresql_nulls_not_distinct=True,
    ),
    comment=(
        "ISSN des revues. Sans revue : ISSN vérifié au Sudoc, dont la publication est absente de la base."
    ),
    schema="publishing",
)


serial_name_forms = Table(
    "serial_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("serial_id", Integer, nullable=False),
    Column("form_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("publisher_id", Integer),
    UniqueConstraint("form_normalized", "publisher_id", name="uq_serial_name_forms_form_publisher"),
    schema="publishing",
)


serial_doi_namespaces = Table(
    "serial_doi_namespaces",
    metadata,
    Column("namespace", Text, primary_key=True),
    Column("serial_id", Integer, nullable=False),
    Column("dois", Integer, nullable=False),
    Column("share", Float, nullable=False),
    schema="publishing",
)


monographs = Table(
    "monographs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text, nullable=False),
    Column(
        "proceedings",
        Boolean,
        nullable=False,
        server_default="false",
        comment="Vrai pour un volume d'actes de congrès, faux pour un livre.",
    ),
    Column(
        "year",
        Integer,
        comment="Année de publication. Elle classe les volumes d'actes d'un même congrès.",
    ),
    Column("isbn", Text),
    Column("eisbn", Text),
    Column("publisher_id", Integer),
    Column(
        "serial_id",
        Integer,
        comment="Collection dont la monographie fait partie, quand cette collection porte un ISSN.",
    ),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("isbn", name="monographs_isbn_key"),
    UniqueConstraint("eisbn", name="monographs_eisbn_key"),
    schema="publishing",
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
    # revues). Maintenu par le pipeline + aux fusions admin. Cf. `serials.publication_count`.
    Column("publication_count", Integer, nullable=False, server_default="0"),
    UniqueConstraint("openalex_id", name="publishers_openalex_id_key"),
    schema="publishing",
)


publisher_name_forms = Table(
    "publisher_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("publisher_id", Integer, nullable=False),
    Column("form_normalized", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("form_normalized", name="publisher_name_forms_form_normalized_key"),
    schema="publishing",
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
    Column("crossref_checked_at", DateTime(timezone=True)),
    Column("datacite_checked_at", DateTime(timezone=True)),
    schema="publishing",
)


# ── Enums Postgres communs ────────────────────────────────────────


identifier_status_enum = PgEnum(
    *(s.value for s in AttributionStatus),
    name="identifier_status",
    create_type=False,
)

# Provenance d'un identifiant : posé par une utilisatrice, ou promu depuis les contributions sources. Le
# vocabulaire vit ici, le domaine ne le déclarant pas.
identifier_origin_enum = PgEnum(
    "manual",
    "auto",
    name="identifier_origin",
    create_type=False,
)

source_type_enum = PgEnum(*ALL_SOURCES, name="source_type", create_type=False)
lookup_source_enum = PgEnum(*LOOKUP_SOURCES, name="lookup_source", create_type=False)

# Tout statut open access est classable par ouverture : les clés d'`OA_RANK` sont le vocabulaire.
oa_type_enum = PgEnum(*OA_RANK, name="oa_type", create_type=False)

license_type_enum = PgEnum(*License, name="license_type", create_type=False)

platform_type_enum = PgEnum(*PLATFORM_TYPES, name="platform_type", create_type=False)

perimeter_evidence_enum = PgEnum(*PerimeterEvidence, name="perimeter_evidence", create_type=False)

doc_type_enum = PgEnum(*DOC_TYPES, name="doc_type", create_type=False)


# ── Adresses ──────────────────────────────────────────────────────


addresses = Table(
    "addresses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("raw_text", Text, nullable=False),
    Column("normalized_text", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("publication_count", Integer, server_default="0"),
    Column("countries", ARRAY(CHAR(2))),
    # Index UNIQUE sur expression md5(normalized_text) — complété à la main, hors
    # de portée de --autogenerate qui ne sait pas représenter l'expression.
    schema="structures",
)


country_detection_method_enum = PgEnum(
    *CountryDetectionMethod, name="country_detection_method", create_type=False
)

address_country_candidates = Table(
    "address_country_candidates",
    metadata,
    Column("address_id", Integer, primary_key=True),
    Column("country_code", CHAR(2), primary_key=True),
    Column("method", country_detection_method_enum, primary_key=True),
    Column("detected_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    schema="structures",
    comment=(
        "Pays proposé pour une adresse par un moyen de détection. addresses.countries en dérive"
        " par la préséance du domaine."
    ),
)


place_name_forms = Table(
    "place_name_forms",
    metadata,
    Column("id", Integer, primary_key=True),
    # `iso_code` en minuscule (cf. countries.code / addresses.countries).
    Column("iso_code", Text, nullable=False),
    Column("form_normalized", Text, nullable=False),
    # `country` (noms de pays, détectés en fin d'adresse) | `institution` /
    # `city` (lieux détectés n'importe où, via la passe place). Défaut `country` :
    # cas d'usage principal (résolution d'un nom de pays vers son code ISO).
    Column("kind", Text, nullable=False, server_default=PlaceNameKind.COUNTRY.value),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("form_normalized", name="place_name_forms_form_normalized_key"),
    CheckConstraint(
        f"kind IN ({', '.join(repr(kind.value) for kind in PlaceNameKind)})",
        name="place_name_forms_kind_check",
    ),
    schema="ref",
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
    schema="structures",
)


idref_structures = Table(
    "idref_structures",
    metadata,
    Column("idref_ppn", Text, nullable=False),
    Column("structure_id", Integer, nullable=False),
    Column("matched_form_id", Integer),
    Column("is_confirmed", Boolean),
    PrimaryKeyConstraint("idref_ppn", "structure_id", name="idref_structures_pkey"),
    comment=(
        "Structure interne d'un PPN IdRef de laboratoire partenaire de thèse : détectée par une "
        "forme de nom (matched_form_id), confirmée ou infirmée par l'administration (is_confirmed)."
    ),
    schema="structures",
)


# ── Contributions (groupes et contributions sources) ──────────────────────────


# `contribution_structures` (MATERIALIZED VIEW, migration 3c8e1f5a9d27) relie un groupe de
# contributions sources rattaché à une personne non exclue aux structures de ses membres.
# Pas modélisée dans le metadata SQLAlchemy — tous les accès se font en SQL brut par nom
# (lectures) ou via REFRESH — pour éviter qu'`alembic --autogenerate` tente de la recréer
# en table.
#
# `publication_structures` (MATERIALIZED VIEW, migration 3c8e1f5a9d27) : lien
# publication↔structure dédoublonné, dérivé des groupes d'auteur × `contribution_structures`.
# Sert la facette labos (COUNT par structure sans DISTINCT). Même statut (SQL brut
# + REFRESH dans le pipeline, après `contribution_structures`).


rejected_contributions = Table(
    "rejected_contributions",
    metadata,
    Column("source_record_id", Integer, nullable=False),
    Column("person_id", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
    PrimaryKeyConstraint("source_record_id", "person_id", name="rejected_contributions_pkey"),
    schema="persons",
)


grouping_method_enum = PgEnum(*GroupingMethod, name="grouping_method", create_type=False)

resolution_mode_enum = PgEnum(*GroupMatchReason, name="resolution_mode", create_type=False)

contributions = Table(
    "contributions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("publication_id", Integer, nullable=False),
    Column("person_id", Integer),
    Column("resolution_mode", resolution_mode_enum),
    Column("reference_position", SmallInteger),
    Column("is_corresponding", Boolean),
    Column("roles", ARRAY(Text)),
    # Indices de l'entrée dans le périmètre, union de ceux des membres ; `in_perimeter` en découle.
    Column(
        "perimeter_evidence",
        ARRAY(perimeter_evidence_enum),
        nullable=False,
        server_default="{}",
    ),
    Column(
        "in_perimeter",
        Boolean,
        Computed("cardinality(perimeter_evidence) > 0", persisted=True),
        nullable=False,
    ),
    UniqueConstraint("publication_id", "person_id", name="contributions_publication_person_uq"),
    CheckConstraint(
        "(person_id IS NULL) = (resolution_mode IS NULL)",
        name="contributions_resolution_mode_with_person",
    ),
    comment=(
        "Contributions sources d'un même auteur dans une publication, avec au maximum une "
        "contribution source par enregistrement source. reference_position : position dans la "
        "liste la plus longue. Une personne correspond au maximum à un groupe par publication."
    ),
    schema="publications",
    # Place gardée dans chaque page pour les mises à jour HOT des attributs et de `reference_position`.
    postgresql_with={"fillfactor": 90},
)


aligned_source_contributions = Table(
    "aligned_source_contributions",
    metadata,
    Column("source_contribution_id", Integer, primary_key=True),
    Column("contribution_id", Integer, nullable=False),
    Column("source_record_id", Integer, nullable=False),
    Column("method", grouping_method_enum, nullable=False),
    Column("score", REAL),
    Column("margin", REAL),
    UniqueConstraint(
        "contribution_id",
        "source_record_id",
        name="aligned_source_contributions_contribution_record_uq",
    ),
    CheckConstraint(
        "method = 'model' OR (score IS NULL AND margin IS NULL)",
        name="aligned_source_contributions_score_check",
    ),
    comment=(
        "Appartenance d'une contribution source à son groupe. method : origine du lien. score et "
        "margin, en bits, pour method = model : poids de Fellegi-Sunter du lien, et écart à la "
        "meilleure autre possibilité de l'affectation."
    ),
    schema="publications",
)

# `publication_author_alignment` (MATERIALIZED VIEW, migration 5c1d8e3a7f20) : recouvrement des
# listes d'auteurs de chaque publication à plusieurs enregistrements sources, dérivé des groupes de contributions sources.
# Sert la file des fusions suspectes. SQL brut + REFRESH en fin de phase `author_grouping`.


# Informations du contributeur dédupliquées : la clé (nom et prénom normalisés,
# identifiants) est extraite des contributions sources (une ligne
# pour ~35 contributions sources). L'unique est `NULLS NOT DISTINCT` : les lignes sans
# identifiant collapsent sur leur seul nom, sans recourir à un sentinel `'{}'`.
contributor_information = Table(
    "contributor_information",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("last_name_normalized", Text, nullable=False),
    Column("first_name_normalized", Text),
    Column("identifiers", Jsonb),
    # Forme normalisée « prénom nom », parties vides omises.
    Column(
        "author_name_normalized",
        Text,
        Computed(
            "CASE WHEN coalesce(first_name_normalized, '') = '' THEN last_name_normalized"
            " WHEN last_name_normalized = '' THEN first_name_normalized"
            " ELSE first_name_normalized || ' ' || last_name_normalized END",
            persisted=True,
        ),
    ),
    # Hash de la clé des informations du contributeur, chemin de lookup indexé et NULL-safe (un `=` ne
    # matche pas les NULL, un `IS NOT DISTINCT FROM` n'est pas indexable). Les
    # sentinelles E'\x01' (NULL) et E'\x1f' (séparateur) sont impossibles dans un
    # nom normalisé ou un jsonb::text. Respecte le NULLS NOT DISTINCT de l'unique.
    # Aligné sur `key_hash_sql` (pipeline/ingestion/common/source_contribution_store.py).
    Column(
        "key_hash",
        Text,
        Computed(
            r"md5(coalesce((last_name_normalized)::text, E'\x01') || E'\x1f' "
            r"|| coalesce((first_name_normalized)::text, E'\x01') || E'\x1f' "
            r"|| coalesce((identifiers)::text, E'\x01'))",
            persisted=True,
        ),
    ),
    UniqueConstraint(
        "last_name_normalized",
        "first_name_normalized",
        "identifiers",
        name="contributor_information_key",
        postgresql_nulls_not_distinct=True,
    ),
    schema="sources",
)


# Arbitrages admin au grain de la contribution source : la paire (contribution source, personne) que la
# phase `persons` relit comme entrée fixe, sans jamais la re-dériver.
confirmed_source_contributions = Table(
    "confirmed_source_contributions",
    metadata,
    Column("source_contribution_id", Integer, nullable=False),
    Column("person_id", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    PrimaryKeyConstraint("source_contribution_id", name="confirmed_source_contributions_pkey"),
    schema="persons",
)


source_contributions = Table(
    "source_contributions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", source_type_enum, nullable=False),
    Column("source_record_id", Integer, nullable=False),
    Column("author_position", SmallInteger),
    # Indices de l'entrée dans le périmètre ; `in_perimeter` en découle.
    Column(
        "perimeter_evidence",
        ARRAY(perimeter_evidence_enum),
        nullable=False,
        server_default="{}",
    ),
    Column(
        "in_perimeter",
        Boolean,
        Computed("cardinality(perimeter_evidence) > 0", persisted=True),
        nullable=False,
    ),
    Column(
        "countries",
        ARRAY(Text),
        comment=(
            "Pays de la contribution source : pays retenus de ses adresses, de ses organisations ROR "
            "sans adresse et de ses structures HAL."
        ),
    ),
    Column(
        "collective",
        Boolean,
        nullable=False,
        server_default="false",
        comment=(
            "Contribution source collective (collaboration, consortium, groupe d'étude…), posée par "
            "la normalisation d'après le signal de la source ou d'après le nom."
        ),
    ),
    Column(
        "duplicate_of",
        Integer,
        comment=(
            "Doublon d'auteur : contribution source qui répète, dans la liste d'auteurs de son "
            "enregistrement source, la contribution source référencée. Écrite par la phase "
            "author_grouping."
        ),
    ),
    Column("is_corresponding", Boolean, server_default="false"),
    Column("roles", ARRAY(Text), server_default="{author}"),
    # Nom tel que la source le donne : nom et prénom séparés, ou chaîne brute
    # (contrainte `source_contributions_name_form`).
    Column("raw_author_name", Text),
    Column("raw_last_name", Text),
    Column("raw_first_name", Text),
    # FK vers `contributor_information` (informations dédupliquées : nom normalisé +
    # identifiants observés de la contribution source). La contrainte FK n'est pas
    # modélisée ici (pattern du projet : les FK vivent en DB, pas dans la
    # MetaData).
    Column("contributor_information_id", Integer, nullable=False),
    Column(
        "neutralized_identifiers",
        Jsonb,
        comment=(
            "Identifiants des informations du contributeur que la résolution des personnes ignore "
            'pour cette contribution source, avec leur motif : {"orcid": "shared"}.'
        ),
    ),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column(
        "content_hash",
        Text,
        comment="Empreinte des champs écrits par la normalisation, adresses comprises.",
    ),
    CheckConstraint(
        "num_nonnulls(raw_author_name, raw_last_name) = 1"
        " AND (raw_first_name IS NULL OR raw_last_name IS NOT NULL)",
        name="source_contributions_name_form",
    ),
    # Vérifiée en fin d'instruction : la mise à jour des contributions sources d'un enregistrement source permute des positions en une seule instruction.
    UniqueConstraint(
        "source_record_id",
        "author_position",
        name="source_contributions_record_position_key",
        deferrable=True,
        initially="IMMEDIATE",
    ),
    # Index couvrant : `person_id` en tête sert les recherches par personne ;
    # `contributor_information_id` en colonne incluse permet l'index-only scan de la projection
    # `(person_id, identifiants)` de la file « conflits d'identifiant » (admin),
    # qui rejoint `contributor_information` sur `contributor_information_id`.
    schema="sources",
    # Place gardée dans chaque page pour les mises à jour HOT de `countries`, `perimeter_evidence` et `neutralized_identifiers`.
    postgresql_with={"fillfactor": 90},
)


source_contribution_addresses = Table(
    "source_contribution_addresses",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source_contribution_id", Integer, nullable=False),
    Column("address_id", Integer, nullable=False),
    UniqueConstraint(
        "source_contribution_id",
        "address_id",
        name="source_contribution_addresses_key",
    ),
    schema="sources",
)


source_contribution_hal_structures = Table(
    "source_contribution_hal_structures",
    metadata,
    Column("source_contribution_id", Integer, nullable=False),
    Column("hal_structure_id", Integer, nullable=False),
    PrimaryKeyConstraint(
        "source_contribution_id", "hal_structure_id", name="source_contribution_hal_structures_pkey"
    ),
    schema="sources",
)


source_contribution_rors = Table(
    "source_contribution_rors",
    metadata,
    Column("source_contribution_id", Integer, nullable=False),
    Column("ror_id", Text, nullable=False),
    Column("address_id", Integer),
    UniqueConstraint(
        "source_contribution_id",
        "ror_id",
        "address_id",
        name="source_contribution_rors_key",
        postgresql_nulls_not_distinct=True,
    ),
    comment=(
        "ROR attribués par la source à une contribution source, rattachés à l'adresse de leur "
        "affiliation, ou à la seule contribution source quand l'affiliation est sans texte "
        "(address_id vide). ror_id est sans clé étrangère vers ror_organizations : une source "
        "peut citer un ROR absent du dump importé."
    ),
    schema="sources",
)


# `source_contribution_structures` est une MATERIALIZED VIEW (DDL via migration
# e8f1a3c5d7b9), pas une table : dérivée de `source_contribution_addresses ⋈
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
    Column(
        "exclusion",
        person_exclusion_enum,
        comment=(
            "Motif d'exclusion décidé à la main : not_a_person (fausse entité), "
            "out_of_perimeter (personne réelle rattachée au périmètre par erreur). "
            "Nul pour une personne retenue."
        ),
    ),
    schema="persons",
)


hr_records = Table(
    "hr_records",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("person_id", Integer, nullable=False),
    Column("email", Text),
    Column("role_title", Text),
    Column("department_name", Text),
    Column("start_date", Date),
    Column("end_date", Date),
    Column("hr_export_date", Date),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("person_id", name="hr_records_person_id_key"),
    schema="persons",
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
    schema="persons",
)


# Formes de nom désignant une personne. `name_form` est une chaîne « prénom nom »
# normalisée, au format de `contributor_information.author_name_normalized`.
person_name_forms = Table(
    "person_name_forms",
    metadata,
    Column("name_form", Text, nullable=False),
    Column("person_id", Integer, nullable=False),
    Column("sources", ARRAY(Text), nullable=False, server_default="{}"),
    Column("status", identifier_status_enum, nullable=False, server_default="pending"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    PrimaryKeyConstraint("name_form", "person_id", name="person_name_forms_pkey"),
    schema="persons",
)


# ── Publications ──────────────────────────────────────────────────


publications = Table(
    "publications",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text),
    Column("doc_type", doc_type_enum, server_default="other"),
    Column("publication_year", SmallInteger, nullable=False),
    Column("doi", Text),
    Column(
        "doi_prefix",
        Text,
        Computed("split_part(doi, '/', 1)", persisted=True),
        comment="Préfixe du DOI, pour les jointures sur doi_prefixes.",
    ),
    Column("oa_status", oa_type_enum, server_default="unknown"),
    # Licence de la version éditeur, et licence du fichier déposé dans HAL.
    Column("license", license_type_enum),
    Column("deposit_license", license_type_enum),
    Column("serial_id", Integer),
    Column("monograph_id", Integer),
    Column(
        "publisher_id",
        Integer,
        comment="Éditeur à la date de publication : titulaire du préfixe du DOI Crossref, à défaut éditeur des enregistrements sources.",
    ),
    Column("container_title", Text),
    Column("language", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    Column("countries", ARRAY(Text)),
    Column("sources", ARRAY(source_type_enum), nullable=False, server_default="{}"),
    Column("source_extras", Jsonb),
    Column(
        "corrections",
        Jsonb,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("is_retracted", Boolean, nullable=False, server_default="false"),
    # abstract / keywords / topics / biblio sont dans `publications_detail` (1:1) :
    # colonnes grasses lues uniquement par la page détail, sorties pour garder
    # `publications` étroite (scans listes/facettes).
    # Indices des contributions de personnes non exclues, maintenus par la phase `contributions` et à l'exclusion d'une personne. `in_perimeter` en découle ; le filtre de périmètre des listes le lit.
    Column(
        "perimeter_evidence",
        ARRAY(perimeter_evidence_enum),
        nullable=False,
        server_default="{}",
    ),
    Column(
        "in_perimeter",
        Boolean,
        Computed("cardinality(perimeter_evidence) > 0", persisted=True),
        nullable=False,
    ),
    # Date de la dernière ingestion des sujets (NULL = à ingérer), posée par la phase
    # `subjects`, que la publication ait des sujets ou non. L'enregistrement d'une
    # publication recalculée depuis ses sources la remet à NULL.
    Column("subjects_ingested_at", DateTime(timezone=True)),
    # Listes scopées au périmètre : tri par défaut (publication_year DESC) et sous-requêtes
    # publication_count par éditeur/revue (jointure via serial_id), restreints au périmètre.
    # Index UNIQUE sur expression lower(doi) — complété à la main. L'unicité
    # « 1 DOI = 1 publication » est garantie par la DB : la réconciliation des
    # composantes ne produit jamais deux publications au même DOI (assignation à
    # l'unique publication ancre de la partition `(composante ∩ DOI)`). Partiel : les
    # publications sans DOI (NULL) ne sont pas contraintes.
    # Fetch incrémental oa_status : jamais vérifiés (NULL) d'abord, puis les plus périmés.
    CheckConstraint(
        "jsonb_typeof(corrections) = 'object'",
        name="publications_corrections_is_object",
    ),
    schema="publications",
)


# Colonnes grasses detail-only sorties de `publications` (1:1, FK ON DELETE CASCADE
# côté schéma — voir migration). Lues par la page détail et `find_by_id`, écrites
# par `PublicationStore.save` (upsert).
publications_detail = Table(
    "publications_detail",
    metadata,
    Column("publication_id", Integer, primary_key=True),
    Column("abstract", Text),
    Column("keywords", ARRAY(Text)),
    Column("topics", Jsonb),
    Column("biblio", Jsonb),
    schema="publications",
)


source_records = Table(
    "source_records",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", source_type_enum, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("doi", Text),
    Column("title", Text, nullable=False),
    Column("title_normalized", Text),
    Column("publication_year", SmallInteger),
    Column("doc_type", doc_type_enum),
    Column(
        "raw_doc_type",
        Text,
        comment="Type de document donné par la source, dans son vocabulaire.",
    ),
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
        Jsonb,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column("urls", ARRAY(Text)),
    Column("impact", Jsonb),
    Column("serial_id", Integer),
    Column("monograph_id", Integer),
    Column(
        "publisher_id",
        Integer,
        comment="Éditeur que nomme la source. Nul pour une production hébergée sans être publiée.",
    ),
    Column("oa_status", Text),
    # Licence normalisée de l'enregistrement source ; la forme brute reste dans `source_extras`.
    Column("license", license_type_enum),
    Column("embargo_until", Date),
    Column("language", Text),
    Column(
        "raw_language",
        Text,
        comment="Langue donnée par la source, dans son vocabulaire.",
    ),
    Column("container_title", Text),
    Column("is_retracted", Boolean),
    Column("abstract", Text),
    Column("keywords", ARRAY(Text)),
    Column("topics", Jsonb),
    Column("biblio", Jsonb),
    Column("source_extras", Jsonb),
    Column(
        "corrections",
        Jsonb,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    ),
    Column(
        "authors_hash",
        Text,
        comment=(
            "Empreinte de la partie auteurs du payload source, à la dernière synchronisation des "
            "contributions sources."
        ),
    ),
    Column(
        "author_count",
        Integer,
        nullable=False,
        server_default="0",
        comment=(
            "Contributions sources de l'enregistrement source qui ont le rôle author et ne sont pas "
            "collectives, telles que la source les donne."
        ),
    ),
    Column(
        "distinct_author_count",
        Integer,
        nullable=False,
        server_default="0",
        comment=(
            "Noms complets normalisés distincts parmi les contributions sources comptées par "
            "author_count."
        ),
    ),
    UniqueConstraint("source", "source_id", name="source_records_source_source_id_key"),
    CheckConstraint(
        "jsonb_typeof(external_ids) = 'object'",
        name="source_records_external_ids_is_object",
    ),
    CheckConstraint(
        "impact IS NULL OR jsonb_typeof(impact) = 'object'",
        name="source_records_impact_is_object",
    ),
    CheckConstraint(
        "jsonb_typeof(corrections) = 'object'",
        name="source_records_corrections_is_object",
    ),
    schema="sources",
)


platforms = Table(
    "platforms",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", Text, nullable=False),
    Column("name_normalized", Text, nullable=False),
    Column("platform_type", platform_type_enum, nullable=False, server_default="unknown"),
    Column(
        "openalex_id",
        Text,
        comment="Source OpenAlex de la plateforme, dont elle prend le nom.",
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("openalex_id", name="platforms_openalex_id_key"),
    schema="publishing",
    comment="Lieux qui hébergent des publications : entrepôts, serveurs de preprints, plateformes d'éditeurs.",
)


source_record_locations = Table(
    "source_record_locations",
    metadata,
    Column("source_record_id", Integer, primary_key=True),
    Column("url", Text, primary_key=True),
    Column("pdf_url", Text),
    Column("oai_id", Text, comment="Identifiant OAI-PMH de la copie, que déclare l'entrepôt."),
    Column(
        "version",
        Text,
        comment="Version de la copie dans le vocabulaire de la source (submittedVersion, acceptedVersion, publishedVersion).",
    ),
    Column("license", license_type_enum),
    Column("is_oa", Boolean),
    Column("platform_id", Integer),
    schema="sources",
    comment="Localisations d'un enregistrement source, réécrites à chaque normalisation.",
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
    schema="persons",
)


# Relevés de paiements de frais de publication (Article Processing Charges) :
# une ligne par paiement, importés depuis des exports comptables (colonnes à
# plat ; `source_file` trace le fichier d'origine). `publication_id`,
# `serial_id`, `publisher_id` et `*_structure_id` sont rapprochés après import.
apc_payments = Table(
    "apc_payments",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("lab_name", Text),
    Column("publisher_name", Text),
    Column("journal_name", Text),
    Column("issn", Text),
    Column("doi", Text),
    Column("amount_eur_ht", Numeric(12, 2)),
    Column("billing_year", SmallInteger),
    Column("publication_year", SmallInteger),
    Column("budget", Text),
    Column("institution", Text),
    Column("coman_id", Integer),
    Column("source_file", Text),
    Column("remarks", Text),
    Column("publication_id", Integer),
    Column("serial_id", Integer),
    Column("publisher_id", Integer),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("budget_structure_id", Integer),
    Column("lab_structure_id", Integer),
    Column(
        "open_access_fee",
        Boolean,
        nullable=False,
        comment=(
            "Vrai pour un frais d'open access (Open APC), faux pour un autre frais de "
            "publication (enquête, frais hors OA)."
        ),
    ),
    UniqueConstraint(
        "doi", "institution", "amount_eur_ht", "open_access_fee", name="apc_payments_payment_key"
    ),
    # Index sur expression lower(doi) — complété à la main.
    schema="publishing",
)


countries = Table(
    "countries",
    metadata,
    Column("code", CHAR(2), primary_key=True),
    Column("name", Text, nullable=False),
    schema="ref",
)


languages = Table(
    "languages",
    metadata,
    Column("code", Text, primary_key=True),
    Column("name", Text, nullable=False),
    comment=(
        "Référentiel des langues. code : ISO 639-1, ou ISO 639-3 pour une langue sans code "
        "à deux lettres. name : nom français, affiché."
    ),
    schema="ref",
)


language_forms = Table(
    "language_forms",
    metadata,
    Column("form_normalized", Text, primary_key=True),
    Column("language_code", Text, nullable=False),
    comment=(
        "Formes sous lesquelles les sources désignent une langue, en minuscules : codes à deux "
        "et trois lettres, nom anglais."
    ),
    schema="ref",
)


staging = Table(
    "staging",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("source", source_type_enum, nullable=False),
    Column("source_id", Text, nullable=False),
    Column("doi", Text),
    Column("raw_data", Jsonb, nullable=False),
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
            "normalisées. Cas particulier OpenAlex : `fetch_truncated` n'écrit PAS "
            "`raw_hash` quand il complète les authorships d'une publication tronquée "
            "à 100 — la ligne garde le hash du payload bulk pour que le bulk suivant "
            "ne déclenche pas de réécriture inutile."
        ),
    ),
    Column("last_seen_at", DateTime(timezone=True), server_default=func.now()),
    Column("disappeared_at", DateTime(timezone=True)),
    # OpenAlex : payload bulk plafonné à 100 auteurs → work probablement tronqué.
    # Posé à l'extraction, consommé puis effacé par `fetch_truncated`.
    Column("authors_truncated", Boolean, nullable=False, server_default="false"),
    # Provenance d'entrée : vocabulaire `StagingEntryMode`.
    Column("entry_mode", Text, nullable=False, server_default=StagingEntryMode.BULK.value),
    UniqueConstraint("source", "source_id", name="staging_source_source_id_key"),
    CheckConstraint(
        "entry_mode = ANY (ARRAY["
        + ", ".join(f"'{mode.value}'::text" for mode in StagingEntryMode)
        + "])",
        name="staging_entry_mode_check",
    ),
    comment=(
        "Documents moissonnés, en transit vers les tables sources. Deux états : à traiter "
        "(processed FALSE, raw_data porte le payload de la source), normalisée (processed "
        "TRUE, raw_data vidé)."
    ),
    schema="sources",
)


failed_lookups = Table(
    "failed_lookups",
    metadata,
    Column("source", lookup_source_enum, nullable=False),
    Column("id_type", Text, nullable=False),
    Column("id_value", Text, nullable=False),
    Column("not_found_at", DateTime(timezone=True), nullable=False),
    PrimaryKeyConstraint("source", "id_type", "id_value"),
    CheckConstraint(
        "id_type = ANY (ARRAY['doi'::text, 'hal_id'::text, 'nnt'::text])",
        name="failed_lookups_id_type_check",
    ),
    comment=(
        "Identifiants cherchés en vain par la phase fetch_missing, dans une source ou auprès de "
        "doi.org (source doi_org : DOI que doi.org ne connaît pas). L'échec est définitif pour un "
        "identifiant absent de son registre (hal-id dans HAL, NNT dans theses.fr, DOI auprès de "
        "doi.org). Les autres recherches reprennent quand not_found_at date de plus que le délai "
        "fetch_missing_retry_after_days."
    ),
    schema="sources",
)


unpaywall = Table(
    "unpaywall",
    metadata,
    Column("doi", Text, primary_key=True),
    Column(
        "oa_status",
        oa_type_enum,
        comment="Statut open access donné par Unpaywall. NULL : DOI absent d'Unpaywall.",
    ),
    Column("checked_at", DateTime(timezone=True), nullable=False),
    comment=(
        "Verdict d'Unpaywall pour chaque DOI interrogé par la phase oa_status. Le DOI est "
        "réinterrogé quand checked_at date de plus que le délai unpaywall_recheck_after_days."
    ),
    schema="sources",
)


subjects = Table(
    "subjects",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("label", Text, nullable=False),
    Column(
        "label_normalized",
        Text,
        nullable=False,
        comment="Forme de recherche du libellé (normalize_text), servie par un index trigram.",
    ),
    Column("language", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("usage_count", Integer, nullable=False, server_default="0"),
    schema="publications",
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
    schema="publications",
)


relation_type_enum = PgEnum(
    *(r.value for r in RelationType),
    name="relation_type",
    create_type=False,
)


# Relations sémantiques entre publications distinctes, dirigées du sujet vers l'objet.
# La cible est une publication du corpus (`target_publication_id`) ou un DOI hors corpus
# (`target_doi`), d'où l'unique `NULLS NOT DISTINCT`, qui dédoublonne sur celle des deux
# qui est renseignée.
publication_relations = Table(
    "publication_relations",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("from_publication_id", Integer, nullable=False),
    Column("relation_type", relation_type_enum, nullable=False),
    Column("target_doi", Text),
    Column("target_publication_id", Integer),
    Column("source", Text, nullable=False),
    CheckConstraint(
        "target_publication_id IS NOT NULL OR target_doi IS NOT NULL",
        name="publication_relations_target_present",
    ),
    UniqueConstraint(
        "from_publication_id",
        "relation_type",
        "target_publication_id",
        "target_doi",
        name="publication_relations_uq",
        postgresql_nulls_not_distinct=True,
    ),
    schema="publications",
)


# Journal d'exécution du pipeline, une ligne par phase et par run : l'admin y lit le
# déroulé, les signaux d'entrée et les métriques de sortie de chaque phase.
pipeline_phase_executions = Table(
    "pipeline_phase_executions",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("run_id", BigInteger, nullable=False),
    Column("phase", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True), nullable=False),
    Column("mode", Text, nullable=False),
    Column("sources", ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")),
    Column("status", Text, nullable=False),
    Column("signals", Jsonb, nullable=False, server_default=text("'[]'::jsonb")),
    Column("metrics", Jsonb, nullable=False, server_default=text("'{}'::jsonb")),
    Column("details", Jsonb, nullable=False, server_default=text("'{}'::jsonb")),
    CheckConstraint(
        "status = ANY (ARRAY['ok'::text, 'warning'::text, 'error'::text])",
        name="pipeline_phase_executions_status_check",
    ),
    schema="ops",
)


# ── Files d'attente de recalcul ───────────────────────────────────
# Identifiants des lignes qu'une tâche du pipeline doit traiter (`infrastructure.db.queues`).


def _queue(name: str) -> Table:
    return Table(
        name,
        metadata,
        Column("id", Integer, primary_key=True),
        Column("seq", BigInteger, Identity(always=True), nullable=False),
        schema="queues",
    )


source_contribution_countries_queue = _queue("source_contribution_countries_queue")
address_countries_queue = _queue("address_countries_queue")
address_candidates_queue = _queue("address_candidates_queue")
publication_contributions_queue = _queue("publication_contributions_queue")
source_record_keys_queue = _queue("source_record_keys_queue")
contribution_attributes_queue = _queue("contribution_attributes_queue")
contribution_resolution_queue = _queue("contribution_resolution_queue")


# `subject_cooccurrences` est une MATERIALIZED VIEW (migration c8a3f2e5b4d7),
# pas une table : paires de sujets co-présents sur une même publication, avec
# leur effectif (seuil `count >= 2`). Non modélisée dans le metadata SQLAlchemy
# — accès en SQL brut par nom (lectures) ou via REFRESH — pour éviter
# qu'`alembic --autogenerate` tente de la recréer en table.
