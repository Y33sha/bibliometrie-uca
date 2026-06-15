"""source_publications.raw_metadata : sidecar JSONB du brut écrasé par correction

Les corrections de métadonnées (doc_type, journal_id, oa_status, doi) sont
désormais persistées **en place** dans les colonnes typées de
`source_publications` : le matcher lit des colonnes nues, indexées, contraintes.
Pour préserver la réversibilité totale (impératif d'inviolabilité des sources),
le brut écrasé est stashé ici, par champ effectivement changé, au format
`{"<champ>": {"raw": <valeur d'origine>, "by": "<règle>"}}`. La présence d'une
clé signale « ce champ a été corrigé » ; reconstruire la source =
`COALESCE(raw_metadata->'<champ>'->>'raw', <colonne>)`.

Objet par défaut `'{}'` (aucune correction), NOT NULL + CHECK is object pour le
même invariant que `external_ids`. Pas d'index : la colonne n'est lue que pour la
réversibilité / l'audit / la réhydratation admin, jamais dans le chemin du match.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "1278fb0fe5b4"
down_revision: str | Sequence[str] | None = "c5f1a9d3e7b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_publications",
        sa.Column(
            "raw_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "source_publications_raw_metadata_is_object",
        "source_publications",
        "jsonb_typeof(raw_metadata) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "source_publications_raw_metadata_is_object",
        "source_publications",
        type_="check",
    )
    op.drop_column("source_publications", "raw_metadata")
