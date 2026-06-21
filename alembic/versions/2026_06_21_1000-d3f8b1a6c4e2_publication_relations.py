"""publication_relations : table des relations entre publications + enum relation_type

Relations sémantiques entre publications distinctes (preprint↔publié,
supplément↔article, data paper↔dataset, erratum/rétractation/concern↔article…).
Le vocabulaire canonique correspond à `domain.publications.relations.RelationType`.

Une relation est stockée depuis la publication qui la déclare (`from_publication_id`,
toujours en corpus) vers un DOI cible (`target_doi`), résolu en `target_publication_id`
quand la cible est elle-même au corpus (sinon NULL). `source` trace la provenance du
signal (source déclarante ou clé partagée).

Revision ID: d3f8b1a6c4e2
Revises: c9e4a1f7b3d2
Create Date: 2026-06-21 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d3f8b1a6c4e2"
down_revision: str | Sequence[str] | None = "c9e4a1f7b3d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE public.relation_type AS ENUM (
            'is_preprint_of', 'has_preprint',
            'is_supplement_to', 'has_supplement',
            'is_part_of', 'has_part',
            'is_correction_of', 'has_correction',
            'is_retraction_of', 'has_retraction',
            'is_concern_about', 'has_concern',
            'is_translation_of', 'has_translation',
            'describes', 'is_described_by'
        )
        """
    )
    op.execute(
        """
        CREATE TABLE public.publication_relations (
            from_publication_id integer NOT NULL
                REFERENCES public.publications(id) ON DELETE CASCADE,
            relation_type public.relation_type NOT NULL,
            target_doi text NOT NULL,
            target_publication_id integer
                REFERENCES public.publications(id) ON DELETE SET NULL,
            source text NOT NULL,
            PRIMARY KEY (from_publication_id, relation_type, target_doi)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_publication_relations_target_pub
            ON public.publication_relations (target_publication_id)
            WHERE target_publication_id IS NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX idx_publication_relations_target_doi "
        "ON public.publication_relations (target_doi)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.publication_relations")
    op.execute("DROP TYPE IF EXISTS public.relation_type")
