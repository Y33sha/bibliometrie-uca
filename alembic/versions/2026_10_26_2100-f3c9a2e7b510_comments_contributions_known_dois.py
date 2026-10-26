"""Commentaires de contributions, aligned_source_contributions et known_dois dans le vocabulaire du modèle

Revision ID: f3c9a2e7b510
Revises: e2b7c5a9d416
Create Date: 2026-10-26 21:00:00.000000

Les commentaires désignent une contribution par son nom, et une ligne de `source_records` comme un enregistrement source.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3c9a2e7b510"
down_revision: str | Sequence[str] | None = "e2b7c5a9d416"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "COMMENT ON TABLE publications.aligned_source_contributions IS "
        "'Appartenance d''une contribution source à sa contribution. method : origine du lien. "
        "score et margin, en bits, pour method = model : poids de Fellegi-Sunter du lien, et écart "
        "à la meilleure autre possibilité de l''affectation.'"
    )
    op.execute(
        "COMMENT ON TABLE publications.contributions IS "
        "'Contributions sources d''un même auteur dans une publication, avec au maximum une "
        "contribution source par enregistrement source. reference_position : position dans la "
        "liste la plus longue. Une personne a au maximum une contribution par publication.'"
    )
    op.execute(
        "COMMENT ON VIEW sources.known_dois IS "
        "'Tous les DOI connus : DOI des enregistrements sources, DOI liés, cibles des relations, "
        "DOI DataCite déduits des identifiants arXiv. publication_id est la publication de "
        "l''enregistrement source, ou la publication d''origine de la relation ; NULL pour un "
        "enregistrement source orphelin.'"
    )


def downgrade() -> None:
    op.execute(
        "COMMENT ON TABLE publications.aligned_source_contributions IS "
        "'Appartenance d''une contribution source à son groupe. method : origine du lien. "
        "score et margin, en bits, pour method = model : poids de Fellegi-Sunter du lien, et écart "
        "à la meilleure autre possibilité de l''affectation.'"
    )
    op.execute(
        "COMMENT ON TABLE publications.contributions IS "
        "'Contributions sources d''un même auteur dans une publication, avec au maximum une "
        "contribution source par enregistrement source. reference_position : position dans la "
        "liste la plus longue. Une personne correspond au maximum à un groupe par publication.'"
    )
    op.execute(
        "COMMENT ON VIEW sources.known_dois IS "
        "'Tous les DOI connus : DOI des notices, DOI liés, cibles des relations, DOI DataCite "
        "déduits des identifiants arXiv. publication_id est la publication de la notice, ou la "
        "publication d''origine de la relation ; NULL pour une notice orpheline.'"
    )
