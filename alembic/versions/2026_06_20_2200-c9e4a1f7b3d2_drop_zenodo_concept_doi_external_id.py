"""Retire la clé obsolète external_ids.zenodo_concept_doi du stock

La résolution concept/version Zenodo via l'API (qui cachait le concept dans
`external_ids.zenodo_concept_doi`) est remplacée par la dérivation du concept
depuis les `relatedIdentifiers` (`IsVersionOf`) du payload DataCite, au moment
de la correction par cluster de DOI. Le cache n'est plus lu — on le retire.

La substitution `doi = concept` déjà persistée en colonne (et son brut stashé
dans `raw_metadata.doi`) n'est pas touchée : elle est re-dérivée et confirmée
par la passe `metadata_correction` au prochain run.

Revision ID: c9e4a1f7b3d2
Revises: b7d3f2a9c1e4
Create Date: 2026-06-20 22:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c9e4a1f7b3d2"
down_revision: str | Sequence[str] | None = "b7d3f2a9c1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE source_publications
        SET external_ids = external_ids - 'zenodo_concept_doi'
        WHERE external_ids ? 'zenodo_concept_doi'
        """
    )


def downgrade() -> None:
    # Nettoyage de données obsolètes : le cache supprimé ne peut pas être reconstruit
    # par un downgrade (il était alimenté par des appels API). No-op.
    pass
