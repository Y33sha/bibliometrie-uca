"""Paiements APC : frais d'open access et frais hors OA, clé d'unicité

`open_access_fee` distingue les frais d'open access (Open APC) des autres frais de publication (enquête, fichier « frais hors OA »). Le payeur d'un frais hors OA, colonne `budget` du fichier, passe dans `institution` : la clé d'unicité porte sur la même colonne pour les deux sources.

Le DOI est ramené à sa forme `10.xxx/…` en minuscules ; une valeur de remplissage (« inconnu », « pas de doi ») devient nulle. La clé d'unicité est le DOI, le payeur, le montant et le type de frais ; les doublons qu'elle désigne sont supprimés, la ligne d'identifiant minimal restant en place. Les colonnes de l'enquête qu'aucune lecture n'utilise, et deux index sans requête, sont supprimés.

Revision ID: d8a4c2f7b915
Revises: c5f1d8a3e604
Create Date: 2026-10-01 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d8a4c2f7b915"
down_revision: str | Sequence[str] | None = "c5f1d8a3e604"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_UPGRADE = r"""
ALTER TABLE public.apc_payments ADD COLUMN open_access_fee boolean;
UPDATE public.apc_payments SET open_access_fee = (source_file IS DISTINCT FROM 'fp_hors_oa');
ALTER TABLE public.apc_payments ALTER COLUMN open_access_fee SET NOT NULL;
COMMENT ON COLUMN public.apc_payments.open_access_fee IS 'Vrai pour un frais d''open access (Open APC), faux pour un autre frais de publication (enquête, frais hors OA).';

UPDATE public.apc_payments
SET doi = replace(lower(substring(doi from '10\.[0-9]+(?:/|%2[fF])\S+')), '%2f', '/')
WHERE doi IS NOT NULL;

UPDATE public.apc_payments SET institution = budget
WHERE source_file = 'fp_hors_oa' AND institution IS NULL;

DELETE FROM public.apc_payments a
USING public.apc_payments b
WHERE a.doi = b.doi
  AND a.institution IS NOT DISTINCT FROM b.institution
  AND a.amount_eur_ht IS NOT DISTINCT FROM b.amount_eur_ht
  AND a.open_access_fee = b.open_access_fee
  AND a.id > b.id;

ALTER TABLE public.apc_payments
    ADD CONSTRAINT apc_payments_payment_key
    UNIQUE (doi, institution, amount_eur_ht, open_access_fee);

ALTER TABLE public.apc_payments
    DROP COLUMN article_title,
    DROP COLUMN institution_type,
    DROP COLUMN all_surveys_answered,
    DROP COLUMN shared_payment,
    DROP COLUMN expense_type,
    DROP COLUMN publisher_type,
    DROP COLUMN journal_type;

DROP INDEX public.idx_apc_billing_year;
DROP INDEX public.idx_apc_institution;
"""

_DOWNGRADE = r"""
CREATE INDEX idx_apc_institution ON public.apc_payments USING btree (institution);
CREATE INDEX idx_apc_billing_year ON public.apc_payments USING btree (billing_year);

ALTER TABLE public.apc_payments
    ADD COLUMN article_title text,
    ADD COLUMN institution_type text,
    ADD COLUMN all_surveys_answered text,
    ADD COLUMN shared_payment text,
    ADD COLUMN expense_type text,
    ADD COLUMN publisher_type text,
    ADD COLUMN journal_type text;

ALTER TABLE public.apc_payments DROP CONSTRAINT apc_payments_payment_key;
ALTER TABLE public.apc_payments DROP COLUMN open_access_fee;
"""


def upgrade() -> None:
    op.execute(_UPGRADE)


def downgrade() -> None:
    op.execute(_DOWNGRADE)
