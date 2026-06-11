"""country_name_forms -> place_name_forms (+ colonne kind)

Élargit la table des formes de noms de pays pour accueillir aussi des noms de
lieux et d'institutions (villes, universités, marqueurs du système de recherche
français, codes postaux), utilisés pour détecter le pays d'adresses
institutionnelles sans pays explicite (cf. chantier DATA_countries-place-names).

Renommage de la table + ses objets dépendants (séquence, contraintes, index),
et ajout d'une colonne `kind` (`country` | `place`). Les formes existantes sont
des noms de pays → `kind = 'country'` (défaut conservé : le seed et la
résolution nom-de-pays → ISO n'ont rien à changer ; les places futures posent
`kind = 'place'` explicitement).

Revision ID: c3e9b1f7a4d2
Revises: f8a2d6c1b9e3
Create Date: 2026-06-11 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c3e9b1f7a4d2"
down_revision: str | Sequence[str] | None = "f8a2d6c1b9e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE country_name_forms RENAME TO place_name_forms")
    op.execute("ALTER SEQUENCE country_name_forms_id_seq RENAME TO place_name_forms_id_seq")
    op.execute(
        "ALTER TABLE place_name_forms "
        "RENAME CONSTRAINT country_name_forms_pkey TO place_name_forms_pkey"
    )
    op.execute(
        "ALTER TABLE place_name_forms "
        "RENAME CONSTRAINT country_name_forms_form_normalized_key "
        "TO place_name_forms_form_normalized_key"
    )
    op.execute("ALTER INDEX idx_cnf_iso RENAME TO idx_pnf_iso")
    op.execute("ALTER TABLE place_name_forms ADD COLUMN kind text NOT NULL DEFAULT 'country'")
    op.execute(
        "ALTER TABLE place_name_forms "
        "ADD CONSTRAINT place_name_forms_kind_check CHECK (kind IN ('country', 'place'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE place_name_forms DROP CONSTRAINT place_name_forms_kind_check")
    op.execute("ALTER TABLE place_name_forms DROP COLUMN kind")
    op.execute("ALTER INDEX idx_pnf_iso RENAME TO idx_cnf_iso")
    op.execute(
        "ALTER TABLE place_name_forms "
        "RENAME CONSTRAINT place_name_forms_form_normalized_key "
        "TO country_name_forms_form_normalized_key"
    )
    op.execute(
        "ALTER TABLE place_name_forms "
        "RENAME CONSTRAINT place_name_forms_pkey TO country_name_forms_pkey"
    )
    op.execute("ALTER SEQUENCE place_name_forms_id_seq RENAME TO country_name_forms_id_seq")
    op.execute("ALTER TABLE place_name_forms RENAME TO country_name_forms")
