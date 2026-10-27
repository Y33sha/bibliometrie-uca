"""Clé étrangère du pays des formes de noms de lieux

Revision ID: e5b2d8f4a1c7
Revises: c8e3f1a6d924
Create Date: 2026-10-27 20:00:00.000000

`place_name_forms.iso_code` référence `countries.code`, au même type `char(2)`.

Les codes absents de `countries` sont corrigés d'abord. Une institution d'un département d'outre-mer reçoit le code de la France, comme les noms de pays de ces départements. Quatre codes faux sont rectifiés, et une forme trop générique pour désigner un pays est supprimée.

Le seed remplit `countries`. La migration `cb20bf77cb40` insère des villes des deux Congo : leurs pays sont ajoutés s'ils manquent, aux noms du seed.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e5b2d8f4a1c7"
down_revision: str | Sequence[str] | None = "c8e3f1a6d924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CORRECTED_CODES = {
    "terres australes et antarctiques francaises": "tf",
    "department of mathematics an najah national university nablus palestine": "ps",
    "institute for transport studies": "gb",
    "department of engineering sciences middle east technical university ankara": "tr",
}


def upgrade() -> None:
    for form, code in _CORRECTED_CODES.items():
        op.execute(
            f"UPDATE ref.place_name_forms SET iso_code = '{code}' WHERE form_normalized = '{form}'"
        )
    op.execute(
        "UPDATE ref.place_name_forms SET iso_code = 'fr' "
        "WHERE iso_code IN ('gf', 'gp', 'mq', 're', 'yt')"
    )
    op.execute(
        "DELETE FROM ref.place_name_forms "
        "WHERE form_normalized = 'animal production research' AND iso_code = 'sf'"
    )
    op.execute(
        "INSERT INTO ref.countries (code, name) "
        "VALUES ('cg', 'Congo'), ('cd', 'Rép. dém. du Congo') ON CONFLICT DO NOTHING"
    )
    op.execute("ALTER TABLE ref.place_name_forms ALTER COLUMN iso_code TYPE char(2)")
    op.execute(
        "ALTER TABLE ref.place_name_forms ADD CONSTRAINT place_name_forms_iso_code_fkey "
        "FOREIGN KEY (iso_code) REFERENCES ref.countries (code)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE ref.place_name_forms DROP CONSTRAINT place_name_forms_iso_code_fkey")
    op.execute("ALTER TABLE ref.place_name_forms ALTER COLUMN iso_code TYPE text")
