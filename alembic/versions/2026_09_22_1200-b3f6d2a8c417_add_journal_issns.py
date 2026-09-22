"""Crée la table journal_issns

Une ligne par ISSN et par revue : support, ISSN-L, statut, ISSN successeur, date de la vérification au Sudoc. Les colonnes `issn`, `eissn`, `issnl`, `rejected_issns` et `sudoc_checked_at` de `journals` passent dans ces lignes, puis sont supprimées.

Une valeur de `rejected_issns` devient une ligne `malformed` quand sa forme ou sa clé de contrôle est fausse, `unverified` sinon : son motif est inconnu, et la vérification Sudoc le donne.

Revision ID: b3f6d2a8c417
Revises: d7e2a4c91b35
Create Date: 2026-09-22 12:00:00.000000
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3f6d2a8c417"
down_revision: str | Sequence[str] | None = "d7e2a4c91b35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FORM = re.compile(r"\d{4}-\d{3}[\dX]")


def _valid(value: str) -> bool:
    """Forme `NNNN-NNNC` et clé de contrôle juste."""
    if not _FORM.fullmatch(value):
        return False
    digits = value.replace("-", "")
    total = sum(int(d) * w for d, w in zip(digits[:7], range(8, 1, -1), strict=True))
    check = (11 - total % 11) % 11
    return digits[7] == ("X" if check == 10 else str(check))


def upgrade() -> None:
    op.execute("CREATE TYPE issn_support AS ENUM ('print', 'electronic', 'other')")
    op.execute(
        "CREATE TYPE issn_status AS ENUM "
        "('active', 'malformed', 'cancelled', 'related_title', 'supplement', 'unverified')"
    )
    op.create_table(
        "journal_issns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issn", sa.Text(), nullable=False),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("journals.id", ondelete="SET NULL")),
        sa.Column(
            "support",
            postgresql.ENUM("print", "electronic", "other", name="issn_support", create_type=False),
        ),
        sa.Column("linking", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "status",
            postgresql.ENUM(
                "active",
                "malformed",
                "cancelled",
                "related_title",
                "supplement",
                "unverified",
                name="issn_status",
                create_type=False,
            ),
            nullable=False,
            server_default="active",
        ),
        sa.Column("replaced_by", sa.Text()),
        sa.Column("sudoc_checked_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        "ALTER TABLE journal_issns ADD CONSTRAINT uq_journal_issns_issn_journal "
        "UNIQUE NULLS NOT DISTINCT (issn, journal_id)"
    )
    op.create_index("idx_journal_issns_journal", "journal_issns", ["journal_id"])
    op.create_index(
        "uq_journal_issns_linking",
        "journal_issns",
        ["journal_id"],
        unique=True,
        postgresql_where=sa.text("linking"),
    )
    op.execute(
        "COMMENT ON TABLE public.journal_issns IS "
        "'ISSN des revues. Sans revue : ISSN vérifié au Sudoc, dont la publication est absente de la base.'"
    )
    op.execute(
        "COMMENT ON COLUMN public.journal_issns.issn IS "
        "'Forme normalisée si la valeur est valide, valeur reçue sinon (statut malformed).'"
    )
    op.execute(
        "COMMENT ON COLUMN public.journal_issns.support IS 'Support de l''ISSN. NULL : inconnu.'"
    )
    op.execute(
        "COMMENT ON COLUMN public.journal_issns.linking IS 'Vrai pour l''ISSN-L de la revue.'"
    )
    op.execute(
        "COMMENT ON COLUMN public.journal_issns.status IS "
        "'active ; malformed (forme ou clé de contrôle fausse) ; cancelled ; related_title (titre "
        "précédent ou suivant) ; supplement ; unverified (valeur mise de côté, motif inconnu).'"
    )
    op.execute(
        "COMMENT ON COLUMN public.journal_issns.replaced_by IS "
        "'ISSN successeur : titre suivant, forme corrigée d''une valeur mal formée.'"
    )
    op.execute(
        "COMMENT ON COLUMN public.journal_issns.sudoc_checked_at IS "
        "'Date de la vérification de l''ISSN au Sudoc. NULL : jamais vérifié.'"
    )

    # ISSN des colonnes, en majuscules : ISSN papier, électronique ou ISSN-L, sur une seule ligne quand ils coïncident.
    op.execute("""
        INSERT INTO journal_issns (issn, journal_id, support, linking, status, sudoc_checked_at)
        SELECT upper(trim(c.v)), j.id,
               CASE WHEN bool_or(c.kind = 'print') THEN 'print'
                    WHEN bool_or(c.kind = 'electronic') THEN 'electronic' END::issn_support,
               bool_or(c.kind = 'linking'),
               'active',
               j.sudoc_checked_at
        FROM journals j
        CROSS JOIN LATERAL (
            VALUES (j.issn, 'print'), (j.eissn, 'electronic'), (j.issnl, 'linking')
        ) AS c(v, kind)
        WHERE c.v IS NOT NULL
        GROUP BY j.id, upper(trim(c.v))
    """)

    # ISSN rejetés : `malformed` à forme ou clé fausse, gardés tels que reçus ; `unverified` sinon, en majuscules, à
    # revérifier au Sudoc.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT j.id, v, j.sudoc_checked_at FROM journals j, unnest(j.rejected_issns) AS v "
            "WHERE NOT EXISTS (SELECT 1 FROM journal_issns i "
            "                  WHERE i.journal_id = j.id AND i.issn = upper(trim(v)))"
        )
    ).all()
    if rows:
        conn.execute(
            sa.text(
                "INSERT INTO journal_issns (issn, journal_id, status, sudoc_checked_at) "
                "VALUES (:issn, :journal_id, CAST(:status AS issn_status), :checked_at) "
                "ON CONFLICT DO NOTHING"
            ),
            [
                {
                    "issn": value.strip().upper() if _valid(value.strip().upper()) else value,
                    "journal_id": journal_id,
                    "status": "unverified" if _valid(value.strip().upper()) else "malformed",
                    "checked_at": None if _valid(value.strip().upper()) else checked_at,
                }
                for journal_id, value, checked_at in rows
            ],
        )

    op.drop_index("idx_journals_issn", "journals")
    op.drop_index("idx_journals_eissn", "journals")
    op.drop_index("idx_journals_issnl", "journals")
    for column in ("issn", "eissn", "issnl", "rejected_issns", "sudoc_checked_at"):
        op.drop_column("journals", column)


def downgrade() -> None:
    op.add_column("journals", sa.Column("issn", sa.Text()))
    op.add_column("journals", sa.Column("eissn", sa.Text()))
    op.add_column("journals", sa.Column("issnl", sa.Text()))
    op.add_column(
        "journals",
        sa.Column(
            "rejected_issns", sa.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'")
        ),
    )
    op.add_column("journals", sa.Column("sudoc_checked_at", sa.DateTime(timezone=True)))
    op.execute("""
        UPDATE journals j
        SET issn = (SELECT i.issn FROM journal_issns i
                    WHERE i.journal_id = j.id AND i.status = 'active' AND i.support = 'print'
                    ORDER BY i.id LIMIT 1),
            eissn = (SELECT i.issn FROM journal_issns i
                     WHERE i.journal_id = j.id AND i.status = 'active' AND i.support = 'electronic'
                     ORDER BY i.id LIMIT 1),
            issnl = (SELECT i.issn FROM journal_issns i WHERE i.journal_id = j.id AND i.linking),
            sudoc_checked_at = (SELECT CASE WHEN bool_and(i.sudoc_checked_at IS NOT NULL)
                                            THEN min(i.sudoc_checked_at) END
                                FROM journal_issns i WHERE i.journal_id = j.id)
    """)
    op.execute("""
        UPDATE journals j
        SET rejected_issns = coalesce((
            SELECT array_agg(i.issn ORDER BY i.issn)
            FROM journal_issns i
            WHERE i.journal_id = j.id AND i.issn NOT IN (
                coalesce(j.issn, ''), coalesce(j.eissn, ''), coalesce(j.issnl, ''))
        ), '{}')
    """)
    op.create_index("idx_journals_issn", "journals", ["issn"])
    op.create_index("idx_journals_eissn", "journals", ["eissn"])
    op.create_index("idx_journals_issnl", "journals", ["issnl"])
    op.drop_table("journal_issns")
    op.execute("DROP TYPE issn_status")
    op.execute("DROP TYPE issn_support")
