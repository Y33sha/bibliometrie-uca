"""Publications à regrouper quand un humain décide du rattachement d'un ORCID ou d'un IdRef, ou corrige le prénom de sa personne

L'alignement des auteurs (`author_grouping`) donne à une signature réduite à des initiales le prénom de la personne à laquelle un humain a rattaché son ORCID ou son IdRef (statut `confirmed` ou `authenticated`). Les déclencheurs posent `authorships_dirty` sur les publications des signatures dont l'identité contient l'identifiant, quand ce rattachement ou ce prénom change. Deux index d'expression servent leur recherche.

Revision ID: 3c6e8a1f5d27
Revises: 9a2c4f6b8d13
Create Date: 2026-10-19 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3c6e8a1f5d27"
down_revision: str | Sequence[str] | None = "9a2c4f6b8d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HUMAN = "('confirmed', 'authenticated')"


def upgrade() -> None:
    for id_type in ("orcid", "idref"):
        op.execute(f"""
            CREATE INDEX author_identifying_keys_{id_type}_idx
                ON sources.author_identifying_keys ((person_identifiers ->> '{id_type}'))
                WHERE person_identifiers ? '{id_type}'
        """)
    op.execute("""
        CREATE FUNCTION public.regroup_identifier_publications(id_type text, id_value text) RETURNS void
            LANGUAGE sql
            AS $$
                UPDATE publications.publications p SET authorships_dirty = true
                FROM sources.source_publications sp
                JOIN sources.source_authorships sa ON sa.source_publication_id = sp.id
                JOIN sources.author_identifying_keys aik ON aik.id = sa.identity_id
                WHERE p.id = sp.publication_id AND NOT p.authorships_dirty
                  AND aik.person_identifiers ? id_type
                  AND aik.person_identifiers ->> id_type = id_value
            $$
    """)
    op.execute("""
        CREATE FUNCTION public.regroup_on_identifier_decision() RETURNS trigger
            LANGUAGE plpgsql
            AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        PERFORM public.regroup_identifier_publications(OLD.id_type, OLD.id_value);
                    ELSE
                        PERFORM public.regroup_identifier_publications(NEW.id_type, NEW.id_value);
                    END IF;
                    RETURN NULL;
                END;
            $$
    """)
    op.execute(f"""
        CREATE TRIGGER trg_regroup_on_identifier_insert
            AFTER INSERT ON persons.person_identifiers FOR EACH ROW
            WHEN (NEW.id_type IN ('orcid', 'idref') AND NEW.status IN {_HUMAN})
            EXECUTE FUNCTION public.regroup_on_identifier_decision()
    """)
    op.execute(f"""
        CREATE TRIGGER trg_regroup_on_identifier_update
            AFTER UPDATE OF status, person_id ON persons.person_identifiers FOR EACH ROW
            WHEN (NEW.id_type IN ('orcid', 'idref')
                  AND (OLD.status IN {_HUMAN} OR NEW.status IN {_HUMAN})
                  AND (OLD.status IS DISTINCT FROM NEW.status OR OLD.person_id IS DISTINCT FROM NEW.person_id))
            EXECUTE FUNCTION public.regroup_on_identifier_decision()
    """)
    op.execute(f"""
        CREATE TRIGGER trg_regroup_on_identifier_delete
            AFTER DELETE ON persons.person_identifiers FOR EACH ROW
            WHEN (OLD.id_type IN ('orcid', 'idref') AND OLD.status IN {_HUMAN})
            EXECUTE FUNCTION public.regroup_on_identifier_decision()
    """)
    op.execute(f"""
        CREATE FUNCTION public.regroup_on_first_name_change() RETURNS trigger
            LANGUAGE plpgsql
            AS $$
                DECLARE
                    ident record;
                BEGIN
                    FOR ident IN
                        SELECT id_type, id_value FROM persons.person_identifiers
                        WHERE person_id = NEW.id AND id_type IN ('orcid', 'idref') AND status IN {_HUMAN}
                    LOOP
                        PERFORM public.regroup_identifier_publications(ident.id_type, ident.id_value);
                    END LOOP;
                    RETURN NULL;
                END;
            $$
    """)
    op.execute("""
        CREATE TRIGGER trg_regroup_on_first_name_change
            AFTER UPDATE OF first_name_normalized ON persons.persons FOR EACH ROW
            WHEN (OLD.first_name_normalized IS DISTINCT FROM NEW.first_name_normalized)
            EXECUTE FUNCTION public.regroup_on_first_name_change()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_regroup_on_first_name_change ON persons.persons")
    for event in ("insert", "update", "delete"):
        op.execute(f"DROP TRIGGER trg_regroup_on_identifier_{event} ON persons.person_identifiers")
    op.execute("DROP FUNCTION public.regroup_on_first_name_change()")
    op.execute("DROP FUNCTION public.regroup_on_identifier_decision()")
    op.execute("DROP FUNCTION public.regroup_identifier_publications(text, text)")
    for id_type in ("orcid", "idref"):
        op.execute(f"DROP INDEX sources.author_identifying_keys_{id_type}_idx")
