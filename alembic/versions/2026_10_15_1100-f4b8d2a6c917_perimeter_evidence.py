"""Indices de l'entrée dans le périmètre

Le type `perimeter_evidence` nomme les indices qui font entrer une signature dans le périmètre : `address` (une adresse de la signature rattachée à une structure du périmètre) et `rh_identity` (identifiant d'une personne RH, document paru pendant son contrat).

- `source_authorship_structures` gagne la colonne `evidence`, qui entre dans son index unique. `authorship_structures` et `publication_structures`, qui en dépendent, sont recréées à l'identique.
- `source_authorships`, `authorships` et `publications` gagnent la colonne `perimeter_evidence`, tableau d'indices. `authorships` réunit les indices de ses signatures, `publications` ceux des signatures de personnes non exclues.
- `in_perimeter` devient une colonne générée, vraie quand `perimeter_evidence` est non vide. Ses index, la statistique étendue des signatures et la vue `candidate_dois` sont recréés.

Le remplissage reprend la règle de la phase `affiliations` à cette révision. Sur la base de production, il redonne exactement le périmètre en place.

Revision ID: f4b8d2a6c917
Revises: e7b3c9d1a254
Create Date: 2026-10-15 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4b8d2a6c917"
down_revision: str | Sequence[str] | None = "e7b3c9d1a254"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_DROP_STRUCTURE_VIEWS = """
    DROP MATERIALIZED VIEW publications.publication_structures;
    DROP MATERIALIZED VIEW publications.authorship_structures;
    DROP MATERIALIZED VIEW sources.source_authorship_structures;
"""

_PERIMETER_OF_EXTRACTION = """
    ps.perimeter_id = (
        SELECT perimeters.id FROM structures.perimeters
        WHERE perimeters.code = (
            SELECT config.value #>> '{}' FROM ops.config WHERE config.key = 'perimeter_extraction'
        )
    )
"""

_SOURCE_AUTHORSHIP_STRUCTURES = f"""
    CREATE MATERIALIZED VIEW sources.source_authorship_structures AS
    SELECT DISTINCT saa.source_authorship_id, ps.structure_id, 'address'::public.perimeter_evidence AS evidence
    FROM sources.source_authorship_addresses saa
    JOIN structures.address_structures ast ON ast.address_id = saa.address_id
    JOIN structures.perimeter_structures ps ON ps.structure_id = ast.structure_id
    WHERE ast.is_confirmed IS DISTINCT FROM false AND {_PERIMETER_OF_EXTRACTION}
    WITH DATA;

    CREATE UNIQUE INDEX source_authorship_structures_pkey
        ON sources.source_authorship_structures (source_authorship_id, structure_id, evidence);
"""

_SOURCE_AUTHORSHIP_STRUCTURES_DOWNGRADE = f"""
    CREATE MATERIALIZED VIEW sources.source_authorship_structures AS
    SELECT DISTINCT saa.source_authorship_id, ps.structure_id
    FROM sources.source_authorship_addresses saa
    JOIN structures.address_structures ast ON ast.address_id = saa.address_id
    JOIN structures.perimeter_structures ps ON ps.structure_id = ast.structure_id
    WHERE ast.is_confirmed IS DISTINCT FROM false AND {_PERIMETER_OF_EXTRACTION}
    WITH DATA;

    CREATE UNIQUE INDEX source_authorship_structures_pkey
        ON sources.source_authorship_structures (source_authorship_id, structure_id);
"""

_DEPENDENT_STRUCTURE_VIEWS = """
    CREATE INDEX idx_source_authorship_structures_structure_id
        ON sources.source_authorship_structures (structure_id);

    CREATE MATERIALIZED VIEW publications.authorship_structures AS
    SELECT DISTINCT a.id AS authorship_id, sas.structure_id
    FROM sources.source_authorship_structures sas
    JOIN sources.source_authorships sa ON sa.id = sas.source_authorship_id
    JOIN sources.source_publications sp ON sp.id = sa.source_publication_id
    JOIN publications.authorships a ON a.publication_id = sp.publication_id AND a.person_id = sa.person_id
    WHERE NOT EXISTS (
        SELECT 1 FROM persons.persons pe WHERE pe.id = a.person_id AND pe.exclusion IS NOT NULL
    )
    WITH DATA;

    CREATE MATERIALIZED VIEW publications.publication_structures AS
    SELECT DISTINCT a.publication_id, aus.structure_id
    FROM publications.authorships a
    JOIN publications.authorship_structures aus ON aus.authorship_id = a.id
    WITH DATA;

    CREATE UNIQUE INDEX authorship_structures_pkey
        ON publications.authorship_structures (authorship_id, structure_id);
    CREATE INDEX idx_authorship_structures_structure_id
        ON publications.authorship_structures (structure_id);
    CREATE UNIQUE INDEX publication_structures_pub_struct
        ON publications.publication_structures (publication_id, structure_id);
    CREATE INDEX idx_publication_structures_structure
        ON publications.publication_structures (structure_id);
"""

_ADD_EVIDENCE = """
    CREATE TYPE public.perimeter_evidence AS ENUM ('address', 'rh_identity');
    ALTER TABLE sources.source_authorships
        ADD COLUMN perimeter_evidence public.perimeter_evidence[] NOT NULL DEFAULT '{}';
    ALTER TABLE publications.authorships
        ADD COLUMN perimeter_evidence public.perimeter_evidence[] NOT NULL DEFAULT '{}';
    ALTER TABLE publications.publications
        ADD COLUMN perimeter_evidence public.perimeter_evidence[] NOT NULL DEFAULT '{}';
"""

# Signatures qui entrent dans le périmètre par l'identité d'une personne RH, à cette révision.
_RH_IDENTITY = " UNION ".join(
    f"""
    SELECT sa_auth.id
    FROM (
        SELECT pi.person_id, pi.id_type::text AS id_type, pi.id_value,
               coalesce(extract(year FROM r.start_date)::int, 0) AS first_year,
               coalesce(extract(year FROM r.end_date)::int, 9999) AS last_year
        FROM persons.person_identifiers pi
        JOIN persons.persons_rh r ON r.person_id = pi.person_id
        WHERE pi.status::text IN ('authenticated', 'confirmed')
    ) pi
    JOIN sources.author_identifying_keys aik ON aik.person_identifiers->>'{id_type}' = pi.id_value
    JOIN sources.source_authorships sa_auth ON sa_auth.identity_id = aik.id
    JOIN sources.source_publications sp_rh ON sp_rh.id = sa_auth.source_publication_id
    WHERE pi.id_type = '{id_type}'
      AND aik.person_identifiers ? '{id_type}'
      AND NOT coalesce(sa_auth.neutralized_identifiers ? '{id_type}', false)
      {sources}
      AND sp_rh.pub_year BETWEEN pi.first_year AND pi.last_year
      AND NOT EXISTS (
          SELECT 1 FROM persons.rejected_authorships rej
          WHERE rej.source_publication_id = sa_auth.source_publication_id AND rej.person_id = pi.person_id
      )
    """
    for id_type, sources in (
        ("orcid", "AND sa_auth.source::text IN ('crossref', 'datacite', 'hal', 'openalex')"),
        ("idref", ""),
        ("hal_person_id", ""),
    )
)

_FILL_EVIDENCE = f"""
    WITH perimeter AS (
        SELECT ps.structure_id
        FROM structures.perimeter_structures ps
        JOIN structures.perimeters p ON p.id = ps.perimeter_id
        WHERE p.code = coalesce(
            (SELECT value #>> '{{}}' FROM ops.config WHERE key = 'perimeter_persons'),
            (SELECT value #>> '{{}}' FROM ops.config WHERE key = 'perimeter_extraction')
        )
    ), evidence AS (
        SELECT sas.source_authorship_id AS id, 'address'::public.perimeter_evidence AS e
        FROM sources.source_authorship_structures sas
        WHERE sas.structure_id IN (SELECT structure_id FROM perimeter)
        UNION
        SELECT id, 'rh_identity'::public.perimeter_evidence FROM ({_RH_IDENTITY}) rh
    ), by_signature AS (
        SELECT id, array_agg(e ORDER BY e) AS evidence FROM evidence GROUP BY id
    )
    UPDATE sources.source_authorships sa
    SET perimeter_evidence = s.evidence
    FROM by_signature s
    WHERE sa.id = s.id;

    WITH by_authorship AS (
        SELECT a.id, array_agg(DISTINCT e ORDER BY e) AS evidence
        FROM publications.authorships a
        JOIN sources.source_publications sd ON sd.publication_id = a.publication_id
        JOIN sources.source_authorships sa ON sa.source_publication_id = sd.id AND sa.person_id = a.person_id
        CROSS JOIN LATERAL unnest(sa.perimeter_evidence) e
        GROUP BY a.id
    )
    UPDATE publications.authorships a
    SET perimeter_evidence = s.evidence
    FROM by_authorship s
    WHERE a.id = s.id;

    WITH by_publication AS (
        SELECT a.publication_id AS id, array_agg(DISTINCT e ORDER BY e) AS evidence
        FROM publications.authorships a
        JOIN persons.persons pe ON pe.id = a.person_id AND pe.exclusion IS NULL
        CROSS JOIN LATERAL unnest(a.perimeter_evidence) e
        GROUP BY a.publication_id
    )
    UPDATE publications.publications p
    SET perimeter_evidence = s.evidence
    FROM by_publication s
    WHERE p.id = s.id;
"""

_DROP_IN_PERIMETER_DEPENDENTS = """
    DROP VIEW sources.candidate_dois;
    DROP STATISTICS sources.source_authorships_orphan_perimeter;
    DROP INDEX publications.idx_authorships_corresponding_uca;
    DROP INDEX publications.idx_authorships_pub_uca;
    DROP INDEX publications.idx_authorships_uca;
    DROP INDEX publications.idx_publications_in_perimeter_journal;
    DROP INDEX publications.idx_publications_in_perimeter_year;
    DROP INDEX sources.idx_sa_in_perimeter;
    DROP INDEX sources.idx_sa_orphan_in_perimeter;
"""

_GENERATED_IN_PERIMETER = """
    ALTER TABLE sources.source_authorships DROP COLUMN in_perimeter;
    ALTER TABLE sources.source_authorships ADD COLUMN in_perimeter boolean NOT NULL
        GENERATED ALWAYS AS (cardinality(perimeter_evidence) > 0) STORED;
    ALTER TABLE publications.authorships DROP COLUMN in_perimeter;
    ALTER TABLE publications.authorships ADD COLUMN in_perimeter boolean NOT NULL
        GENERATED ALWAYS AS (cardinality(perimeter_evidence) > 0) STORED;
    ALTER TABLE publications.publications DROP COLUMN in_perimeter;
    ALTER TABLE publications.publications ADD COLUMN in_perimeter boolean NOT NULL
        GENERATED ALWAYS AS (cardinality(perimeter_evidence) > 0) STORED;
"""

_PLAIN_IN_PERIMETER = """
    ALTER TABLE sources.source_authorships RENAME COLUMN in_perimeter TO in_perimeter_generated;
    ALTER TABLE sources.source_authorships ADD COLUMN in_perimeter boolean DEFAULT false;
    UPDATE sources.source_authorships SET in_perimeter = in_perimeter_generated WHERE in_perimeter_generated;
    ALTER TABLE sources.source_authorships DROP COLUMN in_perimeter_generated;
    ALTER TABLE publications.authorships RENAME COLUMN in_perimeter TO in_perimeter_generated;
    ALTER TABLE publications.authorships ADD COLUMN in_perimeter boolean DEFAULT false;
    UPDATE publications.authorships SET in_perimeter = in_perimeter_generated WHERE in_perimeter_generated;
    ALTER TABLE publications.authorships DROP COLUMN in_perimeter_generated;
    ALTER TABLE publications.publications RENAME COLUMN in_perimeter TO in_perimeter_generated;
    ALTER TABLE publications.publications ADD COLUMN in_perimeter boolean DEFAULT false NOT NULL;
    UPDATE publications.publications SET in_perimeter = in_perimeter_generated WHERE in_perimeter_generated;
    ALTER TABLE publications.publications DROP COLUMN in_perimeter_generated;
"""

_IN_PERIMETER_DEPENDENTS = """
    CREATE INDEX idx_authorships_corresponding_uca ON publications.authorships USING btree (publication_id)
        WHERE is_corresponding = true AND in_perimeter = true;
    CREATE INDEX idx_authorships_pub_uca ON publications.authorships USING btree (publication_id)
        WHERE in_perimeter = true;
    CREATE INDEX idx_authorships_uca ON publications.authorships USING btree (in_perimeter)
        WHERE in_perimeter = true;
    CREATE INDEX idx_publications_in_perimeter_journal ON publications.publications USING btree (journal_id)
        WHERE in_perimeter;
    CREATE INDEX idx_publications_in_perimeter_year ON publications.publications USING btree (pub_year DESC)
        WHERE in_perimeter;
    CREATE INDEX idx_sa_in_perimeter ON sources.source_authorships USING btree (source_publication_id)
        WHERE in_perimeter = true;
    CREATE INDEX idx_sa_orphan_in_perimeter ON sources.source_authorships USING btree (id)
        WHERE person_id IS NULL AND in_perimeter;

    CREATE STATISTICS sources.source_authorships_orphan_perimeter (mcv)
        ON in_perimeter, person_id FROM sources.source_authorships;
    ALTER STATISTICS sources.source_authorships_orphan_perimeter SET STATISTICS 1000;

    CREATE VIEW sources.candidate_dois AS
     SELECT sp.doi, sp.source
       FROM sources.source_publications sp
       JOIN publications.publications p ON p.id = sp.publication_id
      WHERE p.in_perimeter AND sp.doi IS NOT NULL
    UNION
     SELECT d.value AS doi, sp.source
       FROM sources.source_publications sp
       JOIN publications.publications p ON p.id = sp.publication_id
       CROSS JOIN LATERAL jsonb_array_elements_text(sp.external_ids -> 'related_dois') d(value)
      WHERE p.in_perimeter AND jsonb_typeof(sp.external_ids -> 'related_dois') = 'array'
    UNION
     SELECT pr.target_doi AS doi, NULL::public.source_type AS source
       FROM publications.publication_relations pr
       JOIN publications.publications p ON p.id = pr.from_publication_id
      WHERE p.in_perimeter AND pr.target_doi IS NOT NULL
    UNION
     SELECT '10.48550/arxiv.' || lower(sp.external_ids ->> 'arxiv_id') AS doi, sp.source
       FROM sources.source_publications sp
       JOIN publications.publications p ON p.id = sp.publication_id
      WHERE p.in_perimeter AND (sp.external_ids ->> 'arxiv_id') IS NOT NULL;
"""


def upgrade() -> None:
    op.execute(_DROP_STRUCTURE_VIEWS)
    op.execute(_ADD_EVIDENCE)
    op.execute(_SOURCE_AUTHORSHIP_STRUCTURES)
    op.execute(_DEPENDENT_STRUCTURE_VIEWS)
    op.execute(_FILL_EVIDENCE)
    op.execute(_DROP_IN_PERIMETER_DEPENDENTS)
    op.execute(_GENERATED_IN_PERIMETER)
    op.execute(_IN_PERIMETER_DEPENDENTS)
    op.execute("ANALYZE sources.source_authorships")


def downgrade() -> None:
    op.execute(_DROP_STRUCTURE_VIEWS)
    op.execute(_DROP_IN_PERIMETER_DEPENDENTS)
    op.execute(_PLAIN_IN_PERIMETER)
    op.execute(_IN_PERIMETER_DEPENDENTS)
    op.execute("""
        ALTER TABLE sources.source_authorships DROP COLUMN perimeter_evidence;
        ALTER TABLE publications.authorships DROP COLUMN perimeter_evidence;
        ALTER TABLE publications.publications DROP COLUMN perimeter_evidence;
        DROP TYPE public.perimeter_evidence;
    """)
    op.execute(_SOURCE_AUTHORSHIP_STRUCTURES_DOWNGRADE)
    op.execute(_DEPENDENT_STRUCTURE_VIEWS)
    op.execute("ANALYZE sources.source_authorships")
