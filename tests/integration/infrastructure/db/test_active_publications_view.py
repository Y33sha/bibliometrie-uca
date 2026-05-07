"""Garde-fou : la vue SQL ``v_active_publications`` doit refléter
``OUT_OF_SCOPE_DOC_TYPES`` côté Python.

La vue est figée dans une migration, mais sa raison d'être (la liste
des doc_types hors périmètre métier aval) est documentée dans
``domain.publications.scope``. Ce test attrape la divergence
silencieuse si l'une est modifiée sans l'autre.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES


class TestActivePublicationsViewMatchesDomain:
    async def test_view_excludes_exactly_out_of_scope_doc_types(self, sa_conn: AsyncConnection):
        """La définition de la vue doit lister exactement les doc_types de
        ``OUT_OF_SCOPE_DOC_TYPES`` dans son ``NOT IN`` / ``<> ALL``.

        On lit la définition depuis ``pg_catalog.pg_views`` et on extrait
        les valeurs entre apostrophes. Pas de parsing AST SQL — il
        suffit d'identifier les littéraux doc_type exposés dans la
        clause de filtre.
        """
        row = (
            await sa_conn.execute(
                text(
                    "SELECT definition FROM pg_views "
                    "WHERE schemaname = 'public' "
                    "AND viewname = 'v_active_publications'"
                )
            )
        ).one()
        definition: str = row.definition

        import re

        literals_in_view = set(re.findall(r"'([a-z_]+)'::public\.doc_type", definition))
        assert literals_in_view == set(OUT_OF_SCOPE_DOC_TYPES), (
            f"Drift entre v_active_publications ({sorted(literals_in_view)}) "
            f"et OUT_OF_SCOPE_DOC_TYPES ({sorted(OUT_OF_SCOPE_DOC_TYPES)}). "
            f"Modifier les deux ensemble."
        )
