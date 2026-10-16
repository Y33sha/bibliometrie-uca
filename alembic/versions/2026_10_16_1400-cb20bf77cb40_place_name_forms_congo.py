"""Formes de noms des deux Congo : « congo » retirée, villes ajoutées

« Congo » seul désigne aussi bien la République du Congo (`cg`) que la République démocratique du Congo (`cd`). La forme rattachait toute adresse « … Congo » à `cg`. Les formes « republic of the congo », « democratic republic of the congo » et « dr congo » restent. Les principales villes universitaires de chaque pays départagent les deux.

Revision ID: cb20bf77cb40
Revises: f85028312584
Create Date: 2026-10-16 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "cb20bf77cb40"
down_revision: str | Sequence[str] | None = "f85028312584"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CITIES = {
    "brazzaville": "cg",
    "pointe noire": "cg",
    "kinshasa": "cd",
    "lubumbashi": "cd",
    "bukavu": "cd",
    "goma": "cd",
    "kisangani": "cd",
}
_VALUES = ", ".join(f"('{iso}', '{form}', 'city')" for form, iso in _CITIES.items())
_FORMS = ", ".join(f"'{form}'" for form in _CITIES)


def upgrade() -> None:
    op.execute(
        "DELETE FROM ref.place_name_forms WHERE form_normalized = 'congo' AND kind = 'country'"
    )
    op.execute(
        f"INSERT INTO ref.place_name_forms (iso_code, form_normalized, kind) VALUES {_VALUES}"
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM ref.place_name_forms WHERE form_normalized IN ({_FORMS})")
    op.execute(
        "INSERT INTO ref.place_name_forms (iso_code, form_normalized, kind) "
        "VALUES ('cg', 'congo', 'country')"
    )
