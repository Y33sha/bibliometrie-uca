"""Sort les identifiants d'accès aux sources de la table config

Clés d'API OpenAlex et Web of Science, compte ScanR et adresse du polite pool sont des secrets :
ils sont lus depuis l'environnement du processus, comme le mot de passe de la base et la clé de
signature des sessions. La table `config` ne garde que les réglages d'exploitation du pipeline.

Revision ID: e7f3c2a91d64
Revises: a1b2c3d4e5f6
Create Date: 2026-08-25 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e7f3c2a91d64"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CLES = (
    "openalex_api_key",
    "wos_api_key",
    "scanr_username",
    "scanr_password",
    "polite_pool_email",
)


def upgrade() -> None:
    valeurs = ", ".join(f"'{cle}'" for cle in _CLES)
    op.execute(f"DELETE FROM config WHERE key IN ({valeurs})")


def downgrade() -> None:
    """Recrée les lignes, sans valeur : les secrets vivent dans l'environnement."""
    descriptions = {
        "openalex_api_key": "Clé API OpenAlex (remplace le polite pool par email)",
        "wos_api_key": "Clé API Web of Science (Clarivate)",
        "scanr_username": "Identifiant API ScanR (Elasticsearch)",
        "scanr_password": "Mot de passe API ScanR",
        "polite_pool_email": "Email pour le polite pool OpenAlex",
    }
    for cle, description in descriptions.items():
        op.execute(
            "INSERT INTO config (key, value, description) "
            f"VALUES ('{cle}', NULL, '{description}') ON CONFLICT (key) DO NOTHING"
        )
