"""Méthodes d'alignement sans modèle probabiliste

`grouping_method` prend les valeurs `reference`, `name`, `gap` et `unordered`. Les appartenances `identifier` et `order` passent à `name`, les appartenances `model` à `gap`, en attendant le recalcul de l'alignement. Les colonnes `score` et `margin` de `aligned_source_contributions` disparaissent avec leur contrainte.

Revision ID: 8c4e2a6f1b93
Revises: 3e517053df89
Create Date: 2026-11-04 18:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8c4e2a6f1b93"
down_revision: str | Sequence[str] | None = "3e517053df89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "publications.aligned_source_contributions"


def _recreate_type(values: Sequence[str], mapping: dict[str, str]) -> None:
    """Recrée `grouping_method` avec `values`, et convertit la colonne `method` : chaque valeur de `mapping` devient sa cible."""
    op.execute("ALTER TYPE public.grouping_method RENAME TO grouping_method_old")
    op.execute(
        "CREATE TYPE public.grouping_method AS ENUM (" + ", ".join(f"'{v}'" for v in values) + ")"
    )
    cases = " ".join(f"WHEN '{old}' THEN '{new}'" for old, new in mapping.items())
    op.execute(f"""
        ALTER TABLE {_TABLE}
        ALTER COLUMN method TYPE public.grouping_method
        USING (CASE method::text {cases} ELSE method::text END)::public.grouping_method
    """)
    op.execute("DROP TYPE public.grouping_method_old")


def upgrade() -> None:
    op.execute(f"ALTER TABLE {_TABLE} DROP CONSTRAINT aligned_source_contributions_score_check")
    op.execute(f"ALTER TABLE {_TABLE} DROP COLUMN score, DROP COLUMN margin")
    _recreate_type(
        ("reference", "name", "gap", "unordered"),
        {"identifier": "name", "order": "name", "model": "gap"},
    )
    op.execute(
        f"COMMENT ON TABLE {_TABLE} IS"
        " 'Appartenance d''une contribution source à sa contribution. method : origine du lien.'"
    )


def downgrade() -> None:
    _recreate_type(
        ("reference", "name", "identifier", "order", "model"),
        {"gap": "model", "unordered": "model"},
    )
    op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN score real, ADD COLUMN margin real")
    op.execute(f"""
        ALTER TABLE {_TABLE} ADD CONSTRAINT aligned_source_contributions_score_check
        CHECK (method = 'model' OR (score IS NULL AND margin IS NULL))
    """)
    op.execute(
        f"COMMENT ON TABLE {_TABLE} IS"
        " 'Appartenance d''une contribution source à sa contribution. method : origine du lien."
        " score et margin, en bits, pour method = model : poids de Fellegi-Sunter du lien,"
        " et écart à la meilleure autre possibilité de l''affectation.'"
    )
