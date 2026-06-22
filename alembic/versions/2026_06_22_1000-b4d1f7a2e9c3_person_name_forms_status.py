"""person_name_forms.status : validation du lien forme de nom ↔ personne

Statut de validation du couple (name_form, person_id), même énumération que
person_identifiers (identifier_status : pending / confirmed / rejected). Permettra à
terme de bloquer au matching une forme de nom rejetée pour une personne et de préserver
les verdicts humains au recalcul de person_name_forms.

Règle de seed : les formes dérivées du nom et prénom renseignés en base (source
'persons', produites par compute_person_name_forms) sont confirmées d'office — ce sont
les formes canoniques de la personne. Pour « Fifi Brindacier », les formes « fifi
brindacier », « brindacier fifi », « f brindacier » et « brindacier f » sont confirmées
sans autre forme de procès.

Revision ID: b4d1f7a2e9c3
Revises: f1a7c3e9b2d4
Create Date: 2026-06-22 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b4d1f7a2e9c3"
down_revision: str | Sequence[str] | None = "f1a7c3e9b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE person_name_forms "
        "ADD COLUMN status public.identifier_status NOT NULL DEFAULT 'pending'"
    )
    op.execute("UPDATE person_name_forms SET status = 'confirmed' WHERE 'persons' = ANY(sources)")


def downgrade() -> None:
    op.execute("ALTER TABLE person_name_forms DROP COLUMN status")
