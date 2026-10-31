"""ISSN de `source_records.biblio.journal` en liste

Revision ID: c4a7e19d2b56
Revises: bec780bbbff7
Create Date: 2026-10-31 21:00:00.000000

Les clés `issn`, `eissn` et `issnl` de `biblio.journal` deviennent une liste `issns`. Chaque élément contient l'ISSN, et selon le cas son support (`electronic` pour `eissn`) ou l'indicateur ISSN-L (`linking` pour `issnl`). L'ISSN de la clé `issn` reste sans support : plusieurs sources y rangeaient un ISSN de support inconnu.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4a7e19d2b56"
down_revision: str | Sequence[str] | None = "bec780bbbff7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE sources.source_records sr
        SET biblio = jsonb_set(
            sr.biblio, '{journal}',
            (sr.biblio->'journal') - 'issn' - 'eissn' - 'issnl'
            || jsonb_build_object('issns', (
                SELECT coalesce(
                    jsonb_agg(
                        jsonb_strip_nulls(jsonb_build_object(
                            'issn', g.issn,
                            'support', g.support,
                            'linking', CASE WHEN g.linking THEN true END
                        ))
                        ORDER BY g.rank
                    ),
                    CAST('[]' AS jsonb)
                )
                FROM (
                    -- Une valeur donnée sous deux clés (ISSN et ISSN-L) forme un seul élément.
                    SELECT v.issn, max(v.support) AS support, bool_or(v.linking) AS linking,
                           min(v.rank) AS rank
                    FROM (VALUES
                        (1, sr.biblio->'journal'->>'issn', CAST(NULL AS text), false),
                        (2, sr.biblio->'journal'->>'eissn', 'electronic', false),
                        (3, sr.biblio->'journal'->>'issnl', CAST(NULL AS text), true)
                    ) AS v(rank, issn, support, linking)
                    WHERE v.issn IS NOT NULL
                    GROUP BY v.issn
                ) g
            ))
        )
        WHERE sr.biblio->'journal' ?| array['issn', 'eissn', 'issnl']
    """)


def downgrade() -> None:
    # Liste ramenée aux trois clés : le premier ISSN ni électronique ni ISSN-L, le premier électronique, l'ISSN-L.
    op.execute("""
        UPDATE sources.source_records sr
        SET biblio = jsonb_set(
            sr.biblio, '{journal}',
            jsonb_strip_nulls(
                (sr.biblio->'journal') - 'issns'
                || jsonb_build_object(
                    'issn', (SELECT e->>'issn' FROM jsonb_array_elements(sr.biblio->'journal'->'issns') e
                             WHERE coalesce(e->>'support', '') <> 'electronic'
                               AND NOT coalesce(CAST(e->>'linking' AS boolean), false)
                             LIMIT 1),
                    'eissn', (SELECT e->>'issn' FROM jsonb_array_elements(sr.biblio->'journal'->'issns') e
                              WHERE e->>'support' = 'electronic' LIMIT 1),
                    'issnl', (SELECT e->>'issn' FROM jsonb_array_elements(sr.biblio->'journal'->'issns') e
                              WHERE coalesce(CAST(e->>'linking' AS boolean), false) LIMIT 1)
                )
            )
        )
        WHERE sr.biblio->'journal' ? 'issns'
    """)
