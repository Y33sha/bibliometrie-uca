"""structure_type : retrait de la valeur d'enum `__epst_deprecated`

Valeur héritée d'un ancien schéma et plus utilisée nulle part dans le code. Postgres ne supporte pas `ALTER TYPE ... DROP VALUE` directement, donc on recrée l'enum sans la valeur et on bascule la colonne via `USING` cast.

Garde-fou : la migration échoue si une row `structures.structure_type` utilise encore la valeur — il faudrait alors la migrer vers une autre valeur d'enum avant de relancer.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-19 11:30:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | Sequence[str] | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    n = conn.exec_driver_sql(
        "SELECT count(*) FROM structures WHERE structure_type = '__epst_deprecated'"
    ).scalar()
    if n:
        raise RuntimeError(
            f"{n} structures utilisent encore structure_type='__epst_deprecated' "
            "— les migrer vers une autre valeur avant de relancer cette migration."
        )

    op.execute("ALTER TYPE public.structure_type RENAME TO structure_type_old")
    op.execute(
        """
        CREATE TYPE public.structure_type AS ENUM (
            'universite',
            'chu',
            'ecole',
            'labo',
            'equipe',
            'site',
            'autre',
            'onr'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE public.structures
        ALTER COLUMN structure_type TYPE public.structure_type
        USING structure_type::text::public.structure_type
        """
    )
    op.execute("DROP TYPE public.structure_type_old")


def downgrade() -> None:
    op.execute("ALTER TYPE public.structure_type RENAME TO structure_type_old")
    op.execute(
        """
        CREATE TYPE public.structure_type AS ENUM (
            'universite',
            '__epst_deprecated',
            'chu',
            'ecole',
            'labo',
            'equipe',
            'site',
            'autre',
            'onr'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE public.structures
        ALTER COLUMN structure_type TYPE public.structure_type
        USING structure_type::text::public.structure_type
        """
    )
    op.execute("DROP TYPE public.structure_type_old")
