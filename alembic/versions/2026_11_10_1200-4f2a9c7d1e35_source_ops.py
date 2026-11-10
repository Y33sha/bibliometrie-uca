"""Source OPS : familles de brevets de l'Office européen des brevets, à la place de ScanR brevets

Revision ID: 4f2a9c7d1e35
Revises: 83e1e5a8e25f
Create Date: 2026-11-10 12:00:00.000000

Les enregistrements sources, les lignes de `staging` et les recherches infructueuses de ScanR brevets sont supprimés ; les publications perdent la source. La valeur `scanr_patents` des types `source_type` et `lookup_source` devient `ops`. `structures.api_ids` perd la clé `scanr_patents` et gagne la clé `ops` : graphies des déposants, sous leur forme de comparaison, pour l'UCA et pour Clermont Auvergne INP. L'indice `patent_applicant` de `source_contribution_structures` reconnaît un déposant par la forme de comparaison de son nom (`source_extras.patent_applicant_forms`) ; la vue et ses dépendantes sont recréées.

La suppression des données de ScanR brevets est définitive : la migration inverse restaure le schéma, et un nouveau moissonnage de ScanR brevets restaure les données.
"""

import json
from collections.abc import Sequence

from alembic import op

revision: str = "4f2a9c7d1e35"
down_revision: str | Sequence[str] | None = "83e1e5a8e25f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UCA_FORMS = [
    "auvergne universite",
    "pascal universite blaise",
    "the univ of clermont auvergne",
    "the university of clermont auvergne",
    "univ blaise pascal",
    "univ blaise pascal clermont fe",
    "univ blaise pascal clermont ferrand ii",
    "univ blaise pascal clermont ii",
    "univ clermont auvergne",
    "univ d auvergne",
    "univ d auvergne clermont 1 eta",
    "univ d auvergne clermont ferra",
    "univ d auvergne clermont i",
    "univ dauvergne",
    "univ dauvergne clermont 1",
    "univ dauvergne clermont i",
    "universite blaise pascal",
    "universite blaise pascal clermont ferrand ii",
    "universite blaise pascal clermont ii",
    "universite blaise pascal de clermont ferrand",
    "universite clermont auvergne",
    "universite d auvergne",
    "universite d auvergne clermont 1",
    "universite d auvergne clermont 1 etablissement public a caractere scientifique et culturel",
    "universite d auvergne clermont ferrand 1",
    "universite d auvergne clermont i",
    "universiteblaise pascal clermont ii",
]
"""Graphies de l'UCA et des universités fusionnées en elle (Blaise-Pascal, Université d'Auvergne), relevées dans OPS au 2026-11-10."""

_INP_FORMS = [
    "clermont auvergne inp",
    "ecole d ingenieurs sigma clermont",
    "ecole nat superieure de chimie de clermont ferrand",
    "ecole nationale superieure chimie clermont ferrand ensccf",
    "ecole nationale superieure de chimie de clermont ferrand",
    "ecole nationale superieure de chimie de clermont ferrand ensccf",
    "ifma inst francais de mecaniqu",
    "ifma institut francais de mecanique avancee",
    "inst francais de mec avancee ifma",
    "inst francais de mecanique avancee",
    "inst francais de mecanique avancee ifma",
    "institut francais de mecanique avancee",
    "institut francais de mecanique avancee ifma",
    "institut nat polytechnique de clermont auvergne",
    "sigma clermont",
]
"""Graphies de Clermont Auvergne INP et des écoles fusionnées en elle (SIGMA Clermont, ENSCCF, IFMA), relevées dans OPS au 2026-11-10."""

_DELETE_SCANR_PATENTS = """
    DELETE FROM sources.source_records WHERE source = 'scanr_patents';
    DELETE FROM sources.staging WHERE source = 'scanr_patents';
    DELETE FROM sources.failed_lookups WHERE source = 'scanr_patents';
    DELETE FROM persons.rejected_contributions WHERE source = 'scanr_patents';
    DELETE FROM publications.manual_merge_source_records WHERE source = 'scanr_patents';
    DELETE FROM publications.publication_subjects WHERE source = 'scanr_patents';
    UPDATE publications.publications
    SET sources = array_remove(sources, 'scanr_patents')
    WHERE 'scanr_patents' = ANY(sources);
"""

_DROP = """
    DROP MATERIALIZED VIEW publications.publication_rors;
    DROP MATERIALIZED VIEW publications.publication_structures;
    DROP MATERIALIZED VIEW publications.contribution_structures;
    DROP MATERIALIZED VIEW sources.source_contribution_structures;
"""

_SOURCE_CONTRIBUTION_STRUCTURES = """
    CREATE MATERIALIZED VIEW sources.source_contribution_structures AS
    WITH RECURSIVE perimeter AS (
        SELECT ps.structure_id
        FROM structures.perimeter_structures ps
        WHERE ps.perimeter_id = (
            SELECT id FROM structures.perimeters
            WHERE code = (SELECT value #>> '{{}}' FROM ops.config WHERE key = 'perimeter_extraction')
        )
    ),
    hal_match AS (
        SELECT hs.hal_structure_id, s.id AS structure_id
        FROM ref.hal_structures hs
        JOIN structures.structures s ON s.ror_id = hs.ror_id
        UNION
        SELECT hal_structure_id, structure_id
        FROM ref.hal_structures
        WHERE structure_id IS NOT NULL
    ),
    hal_ancestors AS (
        SELECT child_id, parent_id AS ancestor_id, 1 AS depth
        FROM ref.hal_structure_relations
        UNION
        SELECT a.child_id, r.parent_id, a.depth + 1
        FROM hal_ancestors a
        JOIN ref.hal_structure_relations r ON r.child_id = a.ancestor_id
        WHERE a.depth < 10
    ),
    hal_direct AS (
        SELECT DISTINCT sah.source_contribution_id,
            COALESCE(al.hal_structure_id, sah.hal_structure_id) AS hal_structure_id
        FROM sources.source_contribution_hal_structures sah
        LEFT JOIN ref.hal_structure_aliases al ON al.alias_id = sah.hal_structure_id
    ),
    hal_lowest AS (
        SELECT source_contribution_id, hal_structure_id FROM hal_direct
        EXCEPT
        SELECT d.source_contribution_id, a.ancestor_id
        FROM hal_direct d
        JOIN hal_ancestors a ON a.child_id = d.hal_structure_id
    ),
    hal_walk AS (
        SELECT hal_structure_id AS origin_id, hal_structure_id, 0 AS depth
        FROM ref.hal_structures
        UNION
        SELECT w.origin_id, r.parent_id, w.depth + 1
        FROM hal_walk w
        JOIN ref.hal_structure_relations r ON r.child_id = w.hal_structure_id
        WHERE w.depth < 10
          AND NOT EXISTS (SELECT 1 FROM hal_match m WHERE m.hal_structure_id = w.hal_structure_id)
    ),
    hal_reach AS (
        SELECT DISTINCT w.origin_id, m.structure_id
        FROM hal_walk w
        JOIN hal_match m ON m.hal_structure_id = w.hal_structure_id
        WHERE m.structure_id IN (SELECT structure_id FROM perimeter)
    )
    SELECT saa.source_contribution_id, ast.structure_id, 'address'::public.perimeter_evidence AS evidence
    FROM sources.source_contribution_addresses saa
    JOIN structures.address_structures ast ON ast.address_id = saa.address_id
    WHERE ast.is_confirmed IS DISTINCT FROM false
      AND ast.structure_id IN (SELECT structure_id FROM perimeter)
    UNION
    SELECT sar.source_contribution_id, s.id, 'ror'::public.perimeter_evidence
    FROM sources.source_contribution_rors sar
    JOIN structures.structures s ON s.ror_id = sar.ror_id
    WHERE s.id IN (SELECT structure_id FROM perimeter)
      AND sar.address_id IS NULL
      AND NOT EXISTS (
          SELECT 1 FROM sources.source_contribution_addresses saa
          WHERE saa.source_contribution_id = sar.source_contribution_id
      )
    UNION
    SELECT l.source_contribution_id, r.structure_id, 'hal_structure'::public.perimeter_evidence
    FROM hal_lowest l
    JOIN hal_reach r ON r.origin_id = l.hal_structure_id
    UNION
    SELECT sa.id, s.id, 'thesis_institution'::public.perimeter_evidence
    FROM sources.source_records sp
    JOIN sources.source_contributions sa ON sa.source_record_id = sp.id
    JOIN structures.structures s ON (s.api_ids -> 'theses') ? (sp.source_extras ->> 'etablissement_ppn')
    WHERE sp.source = 'theses'
      AND s.id IN (SELECT structure_id FROM perimeter)
    UNION
    SELECT sa.id, ist.structure_id, 'thesis_partner'::public.perimeter_evidence
    FROM sources.source_records sp
    CROSS JOIN LATERAL jsonb_array_elements(sp.source_extras -> 'partenaires') partner(value)
    JOIN structures.idref_structures ist ON ist.idref_ppn = partner.value ->> 'ppn'
    JOIN sources.source_contributions sa
        ON sa.source_record_id = sp.id AND sa.roles && ARRAY['author'::text]
    WHERE sp.source = 'theses'
      AND ist.is_confirmed IS DISTINCT FROM false
      AND (ist.matched_form_id IS NOT NULL OR ist.is_confirmed)
      AND ist.structure_id IN (SELECT structure_id FROM perimeter)
    UNION
    {patent_applicant}
    WITH DATA;

    CREATE UNIQUE INDEX source_contribution_structures_pkey
        ON sources.source_contribution_structures (source_contribution_id, structure_id, evidence);
    CREATE INDEX idx_source_contribution_structures_structure_id
        ON sources.source_contribution_structures (structure_id);
"""

_PATENT_APPLICANT_BY_NAME = """
    SELECT sa.id, s.id, 'patent_applicant'::public.perimeter_evidence
    FROM sources.source_records sp
    CROSS JOIN LATERAL jsonb_array_elements_text(sp.source_extras -> 'patent_applicant_forms') form(value)
    JOIN structures.structures s ON (s.api_ids -> 'ops') ? form.value
    JOIN sources.source_contributions sa ON sa.source_record_id = sp.id
    WHERE sp.source = 'ops'
      AND s.id IN (SELECT structure_id FROM perimeter)
"""

_PATENT_APPLICANT_BY_PAYSAGE = """
    SELECT sa.id, s.id, 'patent_applicant'::public.perimeter_evidence
    FROM sources.source_records sp
    CROSS JOIN LATERAL jsonb_array_elements(sp.source_extras -> 'patent_applicants') applicant(value)
    CROSS JOIN LATERAL jsonb_array_elements_text(applicant.value -> 'ids' -> 'paysage') paysage(id)
    JOIN structures.structures s ON (s.api_ids -> 'scanr_patents') ? paysage.id
    JOIN sources.source_contributions sa ON sa.source_record_id = sp.id
    WHERE sp.source = 'scanr_patents'
      AND s.id IN (SELECT structure_id FROM perimeter)
"""

_DEPENDENTS = """
    CREATE MATERIALIZED VIEW publications.contribution_structures AS
    SELECT DISTINCT m.contribution_id, scs.structure_id
    FROM sources.source_contribution_structures scs
    JOIN publications.aligned_source_contributions m ON m.source_contribution_id = scs.source_contribution_id
    JOIN publications.contributions g ON g.id = m.contribution_id
    JOIN persons.persons pe ON pe.id = g.person_id
    WHERE pe.exclusion IS NULL
    WITH DATA;

    CREATE UNIQUE INDEX contribution_structures_pkey
        ON publications.contribution_structures (contribution_id, structure_id);
    CREATE INDEX idx_contribution_structures_structure_id
        ON publications.contribution_structures (structure_id);

    CREATE MATERIALIZED VIEW publications.publication_structures AS
    SELECT DISTINCT g.publication_id, gs.structure_id
    FROM publications.contributions g
    JOIN publications.contribution_structures gs ON gs.contribution_id = g.id
    WHERE public.is_author_role(g.roles)
    WITH DATA;

    CREATE UNIQUE INDEX publication_structures_publication_structure
        ON publications.publication_structures (publication_id, structure_id);
    CREATE INDEX idx_publication_structures_structure
        ON publications.publication_structures (structure_id);

    CREATE MATERIALIZED VIEW publications.publication_rors AS
    WITH RECURSIVE cited AS (
        SELECT c.publication_id, r.ror_id
        FROM publications.contributions c
        JOIN publications.aligned_source_contributions m ON m.contribution_id = c.id
        JOIN sources.source_contribution_rors r
            ON r.source_contribution_id = m.source_contribution_id
        LEFT JOIN persons.persons pe ON pe.id = c.person_id
        WHERE public.is_author_role(c.roles)
          AND pe.exclusion IS DISTINCT FROM 'not_a_person'
        UNION
        SELECT ps.publication_id, s.ror_id
        FROM publications.publication_structures ps
        JOIN structures.structures s ON s.id = ps.structure_id
        WHERE s.ror_id IS NOT NULL
    ),
    lineage AS (
        SELECT publication_id, ror_id, true AS cited FROM cited
        UNION
        SELECT l.publication_id, rr.parent_ror_id, false
        FROM lineage l
        JOIN ref.ror_relations rr ON rr.child_ror_id = l.ror_id
    )
    SELECT publication_id, ror_id, bool_or(cited) AS cited
    FROM lineage
    GROUP BY publication_id, ror_id
    WITH DATA;

    CREATE UNIQUE INDEX publication_rors_pkey
        ON publications.publication_rors (publication_id, ror_id);
    CREATE INDEX idx_publication_rors_ror ON publications.publication_rors (ror_id);
"""


def _recreate(patent_applicant: str) -> None:
    op.execute(_DROP)
    op.execute(_SOURCE_CONTRIBUTION_STRUCTURES.format(patent_applicant=patent_applicant))
    op.execute(_DEPENDENTS)


def _set_forms(code: str, forms: list[str]) -> None:
    op.execute(
        f"""
        UPDATE structures.structures
        SET api_ids = COALESCE(api_ids, '{{}}'::jsonb) || jsonb_build_object('ops', '{json.dumps(forms)}'::jsonb)
        WHERE code = '{code}'
        """  # noqa: S608 — valeurs écrites dans ce module
    )


def upgrade() -> None:
    op.execute(_DELETE_SCANR_PATENTS)
    op.execute("ALTER TYPE public.source_type RENAME VALUE 'scanr_patents' TO 'ops'")
    op.execute("ALTER TYPE public.lookup_source RENAME VALUE 'scanr_patents' TO 'ops'")
    op.execute(
        "UPDATE structures.structures SET api_ids = api_ids - 'scanr_patents' WHERE api_ids ? 'scanr_patents'"
    )
    _set_forms("uca", _UCA_FORMS)
    _set_forms("inp_clermont", _INP_FORMS)
    _recreate(_PATENT_APPLICANT_BY_NAME)


def downgrade() -> None:
    op.execute("DELETE FROM sources.source_records WHERE source = 'ops'")
    op.execute("DELETE FROM sources.staging WHERE source = 'ops'")
    op.execute("DELETE FROM sources.failed_lookups WHERE source = 'ops'")
    op.execute(
        "UPDATE publications.publications SET sources = array_remove(sources, 'ops') WHERE 'ops' = ANY(sources)"
    )
    op.execute("UPDATE structures.structures SET api_ids = api_ids - 'ops' WHERE api_ids ? 'ops'")
    op.execute("ALTER TYPE public.source_type RENAME VALUE 'ops' TO 'scanr_patents'")
    op.execute("ALTER TYPE public.lookup_source RENAME VALUE 'ops' TO 'scanr_patents'")
    _recreate(_PATENT_APPLICANT_BY_PAYSAGE)
