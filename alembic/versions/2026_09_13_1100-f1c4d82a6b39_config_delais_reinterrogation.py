"""Délais de réinterrogation des sources en configuration

Quatre clés portent, en jours, les délais au-delà desquels le pipeline interroge de nouveau une source : documents non revus (`fetch_stale_after_days`, 90), identifiants introuvables (`fetch_missing_retry_after_days`, 30), statut open access vérifié auprès d'Unpaywall (`unpaywall_recheck_after_days`, 15), fichier du DOAJ (`doaj_refresh_after_days`, 30). Chaque valeur est un nombre entier de jours, au moins un.

Revision ID: f1c4d82a6b39
Revises: e9b3c5d71a42
Create Date: 2026-09-13 11:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1c4d82a6b39"
down_revision: str | Sequence[str] | None = "e9b3c5d71a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DELAY_KEYS = (
    "('doaj_refresh_after_days', 'fetch_missing_retry_after_days', "
    "'fetch_stale_after_days', 'unpaywall_recheck_after_days')"
)

_UPGRADE = f"""
INSERT INTO public.config (key, value, description) VALUES
    ('fetch_stale_after_days', '90',
     'Délai, en jours, au-delà duquel un document non revu est interrogé de nouveau à sa source.'),
    ('fetch_missing_retry_after_days', '30',
     'Délai, en jours, avant de chercher de nouveau un identifiant introuvable dans une source. L''échec sur un identifiant natif de la source est définitif.'),
    ('unpaywall_recheck_after_days', '15',
     'Délai, en jours, avant de vérifier de nouveau le statut open access d''une publication auprès d''Unpaywall.'),
    ('doaj_refresh_after_days', '30',
     'Délai, en jours, avant de télécharger de nouveau le fichier du DOAJ.')
ON CONFLICT (key) DO NOTHING;

ALTER TABLE public.config ADD CONSTRAINT config_delay_is_positive_integer CHECK (
    key NOT IN {_DELAY_KEYS}
    OR (jsonb_typeof(value) = 'number' AND (value)::numeric >= 1
        AND (value)::numeric = trunc((value)::numeric))
);
"""

_DOWNGRADE = f"""
ALTER TABLE public.config DROP CONSTRAINT config_delay_is_positive_integer;

DELETE FROM public.config WHERE key IN {_DELAY_KEYS};
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
