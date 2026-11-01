"""Sujets regroupés par libellé normalisé

Revision ID: 6ebcc420521d
Revises: 89669bd2262b
Create Date: 2026-11-01 16:00:00.000000

La vue matérialisée `subject_labels` regroupe les sujets de même libellé normalisé, tous vocabulaires confondus. Elle donne la forme la plus fréquente du libellé et le nombre de publications, compté en union. `subject_cooccurrences` relie des libellés normalisés. La phase `subjects` rafraîchit les deux vues.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6ebcc420521d"
down_revision: str | Sequence[str] | None = "89669bd2262b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW publications.subject_labels AS
        WITH links AS (
            SELECT DISTINCT s.label_normalized, s.label, ps.publication_id
            FROM publications.publication_subjects ps
            JOIN publications.subjects s ON s.id = ps.subject_id
            WHERE NOT ps.rejected
        ),
        forms AS (
            SELECT DISTINCT ON (label_normalized) label_normalized, label
            FROM links
            GROUP BY label_normalized, label
            ORDER BY label_normalized, count(*) DESC, label
        )
        SELECT f.label_normalized, f.label, count(DISTINCT l.publication_id)::integer AS usage_count
        FROM forms f
        JOIN links l ON l.label_normalized = f.label_normalized
        GROUP BY f.label_normalized, f.label
        WITH DATA;

        CREATE UNIQUE INDEX subject_labels_pkey ON publications.subject_labels (label_normalized);
        CREATE INDEX subject_labels_usage_count_idx
            ON publications.subject_labels (usage_count DESC);

        COMMENT ON MATERIALIZED VIEW publications.subject_labels IS
        'Sujets regroupés par libellé normalisé, tous vocabulaires confondus : forme la plus fréquente du libellé, nombre de publications des liens non rejetés.';

        DROP MATERIALIZED VIEW publications.subject_cooccurrences;

        CREATE MATERIALIZED VIEW publications.subject_cooccurrences AS
        WITH links AS (
            SELECT DISTINCT ps.publication_id, s.label_normalized
            FROM publications.publication_subjects ps
            JOIN publications.subjects s ON s.id = ps.subject_id
            WHERE NOT ps.rejected
        )
        SELECT a.label_normalized AS label_a, b.label_normalized AS label_b,
               count(*)::integer AS count
        FROM links a
        JOIN links b
            ON b.publication_id = a.publication_id AND a.label_normalized < b.label_normalized
        GROUP BY a.label_normalized, b.label_normalized
        HAVING count(*) >= 2
        WITH DATA;

        CREATE UNIQUE INDEX subject_cooccurrences_pkey
            ON publications.subject_cooccurrences (label_a, label_b);
        CREATE INDEX subject_cooccurrences_b_idx ON publications.subject_cooccurrences (label_b);
        CREATE INDEX subject_cooccurrences_count_idx
            ON publications.subject_cooccurrences (count DESC);

        COMMENT ON MATERIALIZED VIEW publications.subject_cooccurrences IS
        'Paires de libellés normalisés de sujets présents ensemble sur au moins deux publications, label_a < label_b.';
    """)


def downgrade() -> None:
    op.execute("""
        DROP MATERIALIZED VIEW publications.subject_cooccurrences;
        DROP MATERIALIZED VIEW publications.subject_labels;

        CREATE MATERIALIZED VIEW publications.subject_cooccurrences AS
        SELECT ps1.subject_id AS subject_a_id, ps2.subject_id AS subject_b_id,
               count(DISTINCT ps1.publication_id)::integer AS count
        FROM publications.publication_subjects ps1
        JOIN publications.publication_subjects ps2
            ON ps1.publication_id = ps2.publication_id AND ps1.subject_id < ps2.subject_id
        WHERE NOT ps1.rejected AND NOT ps2.rejected
        GROUP BY ps1.subject_id, ps2.subject_id
        HAVING count(DISTINCT ps1.publication_id) >= 2
        WITH DATA;

        CREATE UNIQUE INDEX subject_cooccurrences_pkey
            ON publications.subject_cooccurrences (subject_a_id, subject_b_id);
        CREATE INDEX subject_cooccurrences_b_idx
            ON publications.subject_cooccurrences (subject_b_id);
        CREATE INDEX subject_cooccurrences_count_idx
            ON publications.subject_cooccurrences (count DESC);
    """)
