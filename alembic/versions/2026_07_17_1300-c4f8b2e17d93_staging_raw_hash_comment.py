"""staging.raw_hash : le commentaire décrit le hash de détection

Le commentaire de la colonne décrivait une empreinte du payload tel qu'extrait, et renvoyait à
une fiche de chantier. `change_detection_hash` calcule l'empreinte sur une copie du payload
dont le bruit volatil propre à la source est neutralisé : elle ne coïncide donc pas avec
`md5(raw_data)` pour les sources qui ont un normaliseur. Le texte reprend celui que
`infrastructure/db/tables.py` déclare, ce qui rend `alembic check` muet sur cette colonne.

Revision ID: c4f8b2e17d93
Revises: b8e5d3a92c17
Create Date: 2026-07-17 13:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f8b2e17d93"
down_revision: str | Sequence[str] | None = "b8e5d3a92c17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENT = (
    "Empreinte md5 servant de clé de détection de changement à l'UPSERT. "
    "Calculée via `change_detection_hash`, qui neutralise le bruit volatil "
    "propre à la source avant l'empreinte (HAL : horodatage de génération "
    "du TEI `label_xml`) — le payload stocké reste, lui, fidèle à la source. "
    "L'empreinte ne coïncide donc pas avec `md5(raw_data)` pour les sources "
    "normalisées. Cas particulier OpenAlex : `refetch_truncated` n'écrit PAS "
    "`raw_hash` quand il complète les authorships d'une publication tronquée "
    "à 100 — la ligne garde le hash du payload bulk pour que le bulk suivant "
    "ne déclenche pas de réécriture inutile."
)

_PREVIOUS_COMMENT = (
    "Empreinte md5 du payload tel qu'extrait de la source bulk. Sert de clé de détection "
    "de changement à l'UPSERT (et d'empreinte d'intégrité pour le chantier "
    "DATA_raw-data-store). Cas particulier OpenAlex : `refetch_truncated` n'écrit PAS "
    "`raw_hash` quand il complète les authorships d'une publication tronquée à 100 — la "
    "ligne garde le hash du payload bulk pour que le bulk suivant ne déclenche pas de "
    "réécriture inutile. L'invariant `raw_hash = md5(raw_data)` est donc volontairement "
    "rompu sur les lignes OpenAlex refetchées."
)


def upgrade() -> None:
    op.alter_column("staging", "raw_hash", comment=_COMMENT, schema="public")


def downgrade() -> None:
    op.alter_column("staging", "raw_hash", comment=_PREVIOUS_COMMENT, schema="public")
