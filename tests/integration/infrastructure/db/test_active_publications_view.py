"""Garde-fou : la vue SQL ``v_active_publications`` doit refléter
``OUT_OF_SCOPE_DOC_TYPES`` côté Python.

La vue est figée dans une migration, mais sa raison d'être (la liste
des doc_types hors périmètre métier aval) est documentée dans
``domain.publications.scope``. Ce test attrape la divergence
silencieuse si l'une est modifiée sans l'autre.
"""

from sqlalchemy import Connection, text

from domain.publications.scope import OUT_OF_SCOPE_DOC_TYPES


class TestActivePublicationsViewMatchesDomain:
    def test_view_excludes_exactly_out_of_scope_doc_types(self, sa_sync_conn: Connection):
        """La définition de la vue doit lister exactement les doc_types de
        ``OUT_OF_SCOPE_DOC_TYPES`` dans son ``NOT IN`` / ``<> ALL``.

        On lit la définition depuis ``pg_catalog.pg_views`` et on extrait
        les valeurs entre apostrophes. Pas de parsing AST SQL — il
        suffit d'identifier les littéraux doc_type exposés dans la
        clause de filtre.
        """
        row = sa_sync_conn.execute(
            text(
                "SELECT definition FROM pg_views "
                "WHERE schemaname = 'public' "
                "AND viewname = 'v_active_publications'"
            )
        ).one()
        definition: str = row.definition

        import re

        # Postgres normalise la définition stockée et retire le préfixe
        # `public.` (puisque `public` est dans le search_path par défaut)
        # même si schema.sql écrit `::public.doc_type` à l'origine.
        literals_in_view = set(re.findall(r"'([a-z_]+)'::(?:public\.)?doc_type", definition))
        assert literals_in_view == set(OUT_OF_SCOPE_DOC_TYPES), (
            f"Drift entre v_active_publications ({sorted(literals_in_view)}) "
            f"et OUT_OF_SCOPE_DOC_TYPES ({sorted(OUT_OF_SCOPE_DOC_TYPES)}). "
            f"Modifier les deux ensemble."
        )


class TestActivePublicationsViewPerimeter:
    """La vue restreint aussi au périmètre : une publication active sans aucun
    ``source_authorship`` in_perimeter en est exclue."""

    def _make_active_pub(self, conn: Connection, *, in_perimeter: bool) -> int:
        pub = conn.execute(
            text(
                "INSERT INTO publications (title, title_normalized, pub_year, doc_type) "
                "VALUES ('T', 't', 2024, CAST('article' AS doc_type)) RETURNING id"
            )
        ).scalar_one()
        sp = conn.execute(
            text(
                "INSERT INTO source_publications (source, source_id, title, publication_id) "
                "VALUES ('openalex', :sid, 'T', :p) RETURNING id"
            ),
            {"sid": f"W{pub}", "p": pub},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO source_authorships (source, source_publication_id, in_perimeter) "
                "VALUES ('openalex', :sp, :ip)"
            ),
            {"sp": sp, "ip": in_perimeter},
        )
        return pub

    def test_excludes_when_no_in_perimeter_authorship(self, sa_sync_conn: Connection):
        pub = self._make_active_pub(sa_sync_conn, in_perimeter=False)
        present = sa_sync_conn.execute(
            text("SELECT 1 FROM v_active_publications WHERE id = :p"), {"p": pub}
        ).scalar()
        assert present is None

    def test_includes_when_in_perimeter_authorship(self, sa_sync_conn: Connection):
        pub = self._make_active_pub(sa_sync_conn, in_perimeter=True)
        present = sa_sync_conn.execute(
            text("SELECT 1 FROM v_active_publications WHERE id = :p"), {"p": pub}
        ).scalar()
        assert present == 1
