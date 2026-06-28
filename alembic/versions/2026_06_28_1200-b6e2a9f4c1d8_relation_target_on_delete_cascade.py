"""publication_relations : target_publication_id en ON DELETE CASCADE

Quand la publication cible d'une relation est supprimée (dissolution d'un orphelin,
absorption par un merge, purge hors fenêtre…), la relation doit disparaître, pas voir sa
cible passée à NULL. L'action `ON DELETE SET NULL` laissait une relation rapprochée par
titre — dont la cible est une publication sans DOI (`target_doi` NULL) — sans aucune cible,
violant le CHECK `publication_relations_target_present`. La nullabilité de `target_doi`
(migration c1a8e4f7b2d9) avait rendu ce conflit possible.

`ON DELETE CASCADE` règle le cas à la source, pour tous les chemins de suppression. Aucune
perte : la phase `relations` purge et reconstruit intégralement les relations par catégorie
de source à chaque exécution ; la table n'est qu'un cache de la dernière dérivation.

Revision ID: b6e2a9f4c1d8
Revises: e7f2a4c6b8d1
Create Date: 2026-06-28 12:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b6e2a9f4c1d8"
down_revision: str | Sequence[str] | None = "e7f2a4c6b8d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.publication_relations "
        "DROP CONSTRAINT publication_relations_target_publication_id_fkey"
    )
    op.execute(
        "ALTER TABLE public.publication_relations "
        "ADD CONSTRAINT publication_relations_target_publication_id_fkey "
        "FOREIGN KEY (target_publication_id) REFERENCES public.publications(id) "
        "ON DELETE CASCADE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.publication_relations "
        "DROP CONSTRAINT publication_relations_target_publication_id_fkey"
    )
    op.execute(
        "ALTER TABLE public.publication_relations "
        "ADD CONSTRAINT publication_relations_target_publication_id_fkey "
        "FOREIGN KEY (target_publication_id) REFERENCES public.publications(id) "
        "ON DELETE SET NULL"
    )
