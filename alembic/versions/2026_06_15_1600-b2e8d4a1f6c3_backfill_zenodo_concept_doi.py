"""backfill : substitution Zenodo concept→colonne doi sur le stock existant

Applique a posteriori, sur le stock, la correction Zenodo désormais portée par la sous-étape `correct_zenodo_concept` de `metadata_correction` : pour chaque `source_publication` au concept DOI caché (`external_ids.zenodo_concept_doi`), écrit le concept **normalisé** dans la colonne `doi`, stashe le DOI source (la version) dans `raw_metadata.doi` (`corrected_by = ZENODO_CONCEPT_DOI`), et marque `keys_dirty` (le DOI change ⇒ réconciliation des composantes au prochain run).

SQL pur (aucun import applicatif). La normalisation du concept duplique `clean_doi` (préfixe URL doi.org, casse, suffixe de version `.vN`, suffixe `/pdf`) — duplication assumée, cf. convention migrations. Idempotent : `doi IS DISTINCT FROM concept` exclut les lignes déjà substituées et les dépôts non versionnés (concept == version).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b2e8d4a1f6c3"
down_revision: str | Sequence[str] | None = "a7c4e9f2b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE source_publications sp
        SET doi = c.concept,
            raw_metadata = sp.raw_metadata || jsonb_build_object(
                'doi', jsonb_build_object(
                    'raw', COALESCE(sp.raw_metadata -> 'doi' ->> 'raw', sp.doi),
                    'corrected_by', 'ZENODO_CONCEPT_DOI'
                )
            ),
            keys_dirty = true
        FROM (
            SELECT id,
                   regexp_replace(
                       regexp_replace(
                           regexp_replace(
                               lower(trim(external_ids ->> 'zenodo_concept_doi')),
                               '^https?://(dx\\.)?doi\\.org/', ''
                           ),
                           '\\.v[0-9]+$', ''
                       ),
                       '/pdf$', ''
                   ) AS concept
            FROM source_publications
            WHERE external_ids ? 'zenodo_concept_doi'
        ) c
        WHERE sp.id = c.id
          AND c.concept IS NOT NULL
          AND c.concept <> ''
          AND sp.doi IS DISTINCT FROM c.concept
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE source_publications
        SET doi = raw_metadata -> 'doi' ->> 'raw',
            raw_metadata = raw_metadata - 'doi'
        WHERE raw_metadata -> 'doi' ->> 'corrected_by' = 'ZENODO_CONCEPT_DOI'
    """)
