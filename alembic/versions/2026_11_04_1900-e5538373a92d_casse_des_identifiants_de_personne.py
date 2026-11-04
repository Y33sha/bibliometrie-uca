"""Casse des identifiants de personne contrainte

Les identifiants de personne ont la casse de leur forme normalisée : idHAL en minuscules, ORCID et IdRef en majuscules. La contrainte porte sur `person_identifiers.id_value` et sur les clés `orcid`, `idref` et `idhal` de `contributor_information.identifiers`.

Les valeurs d'une autre casse sont supprimées avant la pose des contraintes. Une contribution source passe aux informations du contributeur sans ces valeurs, créées au besoin.

Revision ID: e5538373a92d
Revises: 8c4e2a6f1b93
Create Date: 2026-11-04 19:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5538373a92d"
down_revision: str | Sequence[str] | None = "8c4e2a6f1b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CASE_VIOLATIONS = """
    ARRAY_REMOVE(ARRAY[
        CASE WHEN identifiers->>'orcid' <> upper(identifiers->>'orcid') THEN 'orcid' END,
        CASE WHEN identifiers->>'idref' <> upper(identifiers->>'idref') THEN 'idref' END,
        CASE WHEN identifiers->>'idhal' <> lower(identifiers->>'idhal') THEN 'idhal' END
    ], NULL)
"""
"""Clés d'`identifiers` dont la valeur a une autre casse que sa forme normalisée."""


def _delete_case_violations() -> None:
    op.execute("""
        DELETE FROM persons.person_identifiers
        WHERE id_value <> CASE id_type WHEN 'idhal' THEN lower(id_value) ELSE upper(id_value) END
    """)
    op.execute(f"""
        CREATE TEMP TABLE contributor_information_fixes ON COMMIT DROP AS
        SELECT id AS old_id, last_name_normalized, first_name_normalized,
               nullif(identifiers - {_CASE_VIOLATIONS}, '{{}}'::jsonb) AS identifiers
        FROM sources.contributor_information
        WHERE cardinality({_CASE_VIOLATIONS}) > 0
    """)
    op.execute("""
        INSERT INTO sources.contributor_information
            (last_name_normalized, first_name_normalized, identifiers)
        SELECT DISTINCT last_name_normalized, first_name_normalized, identifiers
        FROM contributor_information_fixes
        ON CONFLICT ON CONSTRAINT contributor_information_key DO NOTHING
    """)
    op.execute("""
        UPDATE sources.source_contributions sc
        SET contributor_information_id = ci.id
        FROM contributor_information_fixes f
        JOIN sources.contributor_information ci
          ON ci.last_name_normalized = f.last_name_normalized
         AND ci.first_name_normalized IS NOT DISTINCT FROM f.first_name_normalized
         AND ci.identifiers IS NOT DISTINCT FROM f.identifiers
        WHERE sc.contributor_information_id = f.old_id
    """)
    op.execute("""
        DELETE FROM sources.contributor_information
        WHERE id IN (SELECT old_id FROM contributor_information_fixes)
    """)


def upgrade() -> None:
    _delete_case_violations()
    op.execute("""
        ALTER TABLE persons.person_identifiers ADD CONSTRAINT person_identifiers_id_value_case
            CHECK (id_value = CASE id_type WHEN 'idhal' THEN lower(id_value) ELSE upper(id_value) END)
    """)
    op.execute("""
        ALTER TABLE sources.contributor_information
            ADD CONSTRAINT contributor_information_identifiers_case
            CHECK (
                identifiers->>'orcid' = upper(identifiers->>'orcid')
                AND identifiers->>'idref' = upper(identifiers->>'idref')
                AND identifiers->>'idhal' = lower(identifiers->>'idhal')
            )
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE sources.contributor_information"
        " DROP CONSTRAINT contributor_information_identifiers_case"
    )
    op.execute(
        "ALTER TABLE persons.person_identifiers DROP CONSTRAINT person_identifiers_id_value_case"
    )
