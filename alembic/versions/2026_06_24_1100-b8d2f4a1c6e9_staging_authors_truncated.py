"""staging.authors_truncated : marqueur explicite des works OpenAlex tronqués à 100 auteurs

L'API bulk OpenAlex plafonne la liste des auteurs à 100. Jusqu'ici le refetch
détectait les tronqués par heuristique (`raw_data` à 100 auteurs, `processed=FALSE`),
ce qui les perdait si un document était normalisé sans passer par le refetch
(OpenAlex indisponible, budget API épuisé). Le marqueur est désormais explicite et
posé à l'extraction : il survit à la normalisation (`raw_data` purgé) et rend la
détection indépendante de l'ordre des phases.

Backfill : pose le flag sur les tronqués actuellement détectables — `raw_data` à
100 auteurs (non encore normalisés) et `source_authorships` à 100 (déjà normalisés,
`raw_data` purgé). Les genuine-100 ainsi marqués seront vérifiés une fois par le
refetch puis démarqués.

Revision ID: b8d2f4a1c6e9
Revises: a3f6c1e8b2d4
Create Date: 2026-06-24 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8d2f4a1c6e9"
down_revision: str | Sequence[str] | None = "a3f6c1e8b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE staging ADD COLUMN authors_truncated boolean NOT NULL DEFAULT false")
    # (a) Tronqués non encore normalisés : raw_data présent, 100 authorships.
    op.execute("""
        UPDATE staging
        SET authors_truncated = true
        WHERE source = 'openalex'
          AND jsonb_typeof(raw_data -> 'authorships') = 'array'
          AND jsonb_array_length(raw_data -> 'authorships') = 100
    """)
    # (b) Déjà normalisés (raw_data purgé) : compter via source_authorships.
    op.execute("""
        UPDATE staging s
        SET authors_truncated = true
        FROM (
            SELECT sp.staging_id
            FROM source_publications sp
            JOIN source_authorships sa ON sa.source_publication_id = sp.id
            WHERE sp.source = 'openalex' AND sp.staging_id IS NOT NULL
            GROUP BY sp.id, sp.staging_id
            HAVING count(*) = 100
        ) t
        WHERE s.id = t.staging_id
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE staging DROP COLUMN authors_truncated")
