"""Aligne le commentaire de `staging.raw_hash` sur le nom de la phase

La phase qui complète les works OpenAlex tronqués s'appelle `fetch_truncated`, du nom de
l'opération qu'elle mène — une requête unitaire par identifiant, par opposition aux requêtes
par lots d'`extract`. Le commentaire de colonne portait encore son nom précédent.

Revision ID: e2f5a71c93d8
Revises: d1e6a83f4b52
Create Date: 2026-09-06 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e2f5a71c93d8"
down_revision: str | Sequence[str] | None = "d1e6a83f4b52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COMMENTAIRE = (
    "Empreinte md5 servant de clé de détection de changement à l'UPSERT. "
    "Calculée via `change_detection_hash`, qui neutralise le bruit volatil "
    "propre à la source avant l'empreinte (HAL : horodatage de génération "
    "du TEI `label_xml`) — le payload stocké reste, lui, fidèle à la source. "
    "L'empreinte ne coïncide donc pas avec `md5(raw_data)` pour les sources "
    "normalisées. Cas particulier OpenAlex : {phase} n'écrit PAS "
    "`raw_hash` quand il complète les authorships d'une publication tronquée "
    "à 100 — la ligne garde le hash du payload bulk pour que le bulk suivant "
    "ne déclenche pas de réécriture inutile."
)


def _poser(phase: str) -> None:
    commentaire = _COMMENTAIRE.format(phase=phase).replace("'", "''")
    op.execute(f"COMMENT ON COLUMN staging.raw_hash IS '{commentaire}'")  # noqa: S608


def upgrade() -> None:
    _poser("`fetch_truncated`")


def downgrade() -> None:
    _poser("`refetch_truncated`")
