"""metadata-dedup : fusion rétroactive PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT

Applique la règle PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT (figée dans
`domain.publications.deduplication.MetadataDeduplicationCase`) aux
publications existantes : fusionne les couples détectés par la SQL
d'inventaire (proceedings, même `title_normalized` > 30 car., même
`pub_year`, même `MAX(count source_authorships not excluded)` par
source, au moins un DOI null, hors `distinct_publications`).

Cible = `LEAST(id_a, id_b)`. Source = `GREATEST(id_a, id_b)`. Pour
chaque couple : transfert des `source_publications`, transfert des
`authorships` (dédup par `person_id`), cleanup `distinct_publications`,
DELETE de la pub source. La pub cible est marquée stale (`updated_at`
forcé à l'epoch) pour que `refresh_from_sources` ré-agrège ses méta
canoniques au prochain run du pipeline.

Sur une base sans doublon matching (par ex. base from-scratch), no-op.

Revision ID: b9a2c8d4e7f1
Revises: c7b3e9f1d2a8
Create Date: 2026-05-24 20:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b9a2c8d4e7f1"
down_revision: str | Sequence[str] | None = "c7b3e9f1d2a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        DECLARE
            v_pair RECORD;
            v_target_id INT;
            v_source_id INT;
            v_n_fused INT := 0;
        BEGIN
            FOR v_pair IN
                WITH pub_author_counts AS (
                    SELECT sp.publication_id, MAX(c.n) AS max_n_auth
                    FROM source_publications sp
                    JOIN LATERAL (
                        SELECT COUNT(*) AS n
                        FROM source_authorships sa
                        WHERE sa.source_publication_id = sp.id AND NOT sa.excluded
                    ) c ON true
                    GROUP BY sp.publication_id
                )
                SELECT p1.id AS id_a, p2.id AS id_b
                FROM publications p1
                JOIN publications p2
                  ON p1.id < p2.id
                 AND p1.title_normalized = p2.title_normalized
                 AND p1.pub_year = p2.pub_year
                 AND p1.doc_type = p2.doc_type
                JOIN pub_author_counts c1 ON c1.publication_id = p1.id
                JOIN pub_author_counts c2 ON c2.publication_id = p2.id
                WHERE p1.doc_type = 'proceedings'
                  AND LENGTH(p1.title_normalized) > 30
                  AND c1.max_n_auth = c2.max_n_auth
                  AND NOT (p1.doi IS NOT NULL AND p2.doi IS NOT NULL)
                  AND NOT EXISTS (
                      SELECT 1 FROM distinct_publications dp
                      WHERE dp.pub_id_a = p1.id AND dp.pub_id_b = p2.id
                  )
                ORDER BY p1.id
            LOOP
                v_target_id := LEAST(v_pair.id_a, v_pair.id_b);
                v_source_id := GREATEST(v_pair.id_a, v_pair.id_b);

                -- Résilience aux chaînes : si une pub a déjà été absorbée par
                -- une fusion précédente dans cette même boucle, on saute.
                IF NOT EXISTS (SELECT 1 FROM publications WHERE id = v_source_id)
                   OR NOT EXISTS (SELECT 1 FROM publications WHERE id = v_target_id) THEN
                    CONTINUE;
                END IF;

                -- Transfert des source_publications vers la cible.
                UPDATE source_publications SET publication_id = v_target_id
                WHERE publication_id = v_source_id;

                -- Transfert des authorships canoniques (dédup par person_id).
                DELETE FROM authorships
                WHERE publication_id = v_source_id
                  AND person_id IN (
                      SELECT person_id FROM authorships WHERE publication_id = v_target_id
                  );
                UPDATE authorships SET publication_id = v_target_id
                WHERE publication_id = v_source_id;

                -- Cleanup distinct_publications impliquant la source.
                DELETE FROM distinct_publications
                WHERE pub_id_a = v_source_id OR pub_id_b = v_source_id;

                -- Marque la cible stale pour que refresh_from_sources ré-agrège
                -- les méta canoniques (DOI promu par SOURCE_PRIORITY, etc.)
                -- au prochain run du pipeline.
                UPDATE publications SET updated_at = 'epoch'::timestamptz
                WHERE id = v_target_id;

                -- Suppression de la pub source (ON DELETE CASCADE sur
                -- publication_subjects ; SET NULL sur apc_payments).
                DELETE FROM publications WHERE id = v_source_id;

                v_n_fused := v_n_fused + 1;
                RAISE NOTICE 'PROCEEDINGS_TITLE_YEAR_AUTHORCOUNT : fused % <- %',
                             v_target_id, v_source_id;
            END LOOP;

            RAISE NOTICE 'Total couples fusionnés : %', v_n_fused;
        END $$;
        """
    )


def downgrade() -> None:
    # Les pubs absorbées n'existent plus ; la fusion n'est pas réversible.
    pass
