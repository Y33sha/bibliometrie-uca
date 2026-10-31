"""« URL de résolution » d'un DOI dans les commentaires de `sources.dois` et les descriptions des réglages de doi.org

Revision ID: bec780bbbff7
Revises: 90ef8325f52b
Create Date: 2026-10-31 20:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "bec780bbbff7"
down_revision: str | Sequence[str] | None = "90ef8325f52b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _texts(url: str) -> list[str]:
    """Renvoie les instructions qui écrivent les commentaires et les descriptions, avec `url` pour désigner l'URL vers laquelle le DOI renvoie."""
    return [
        f"""
        COMMENT ON TABLE sources.dois IS
        'Réponses des services externes sur chaque DOI de publication : verdict d''Unpaywall, {url} chez doi.org.'
        """,
        f"""
        COMMENT ON COLUMN sources.dois.registered_url IS
        '{url[0].upper()}{url[1:]} du DOI, lue dans l''API des handles de doi.org. NULL avec une date : DOI inconnu de doi.org.'
        """,
        f"""
        UPDATE ops.config SET description =
        'Nombre maximum de DOI dont l''{url} est lue chez doi.org par run. 0 = illimité.'
        WHERE key = 'doi_resolution_max_per_run'
        """,
        f"""
        UPDATE ops.config SET description =
        'Délai, en jours, avant de relire chez doi.org l''{url} d''un DOI.'
        WHERE key = 'doi_resolution_recheck_after_days'
        """,
    ]


def upgrade() -> None:
    for statement in _texts("URL de résolution"):
        op.execute(statement)


def downgrade() -> None:
    for statement in _texts("adresse enregistrée"):
        op.execute(statement)
