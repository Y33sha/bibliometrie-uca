"""Tests d'intégration de la purge des publications orphelines (zéro authorship).

Garde principale : une publication AVEC authorship n'est jamais supprimée (la
purge ne doit toucher que les orphelines hors-périmètre). Et la cascade
`publication_subjects` confirme que cette table reste scopée périmètre sans
filtre propre.
"""

from sqlalchemy import text

from pipeline.publications.purge_orphan_publications import (
    PurgeOrphanPublicationsQueries,
)
from tests.integration.helpers.authorships import insert_authorship
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.subjects import insert_publication_subject, insert_subject

_Q = PurgeOrphanPublicationsQueries()


class TestPurgeOrphanPublications:
    def test_deletes_pub_without_authorship(self, sa_sync_conn):
        orphan = insert_publication(sa_sync_conn, "orphan")
        _Q.purge_orphan_publications(sa_sync_conn)
        still_there = sa_sync_conn.execute(
            text("SELECT 1 FROM publications WHERE id = :id"), {"id": orphan}
        ).scalar_one_or_none()
        assert still_there is None

    def test_keeps_pub_with_authorship(self, sa_sync_conn):
        kept = insert_publication(sa_sync_conn, "kept")
        person = insert_person(sa_sync_conn, "Doe", first_name="Jane")
        insert_authorship(sa_sync_conn, kept, person_id=person)
        _Q.purge_orphan_publications(sa_sync_conn)
        still_there = sa_sync_conn.execute(
            text("SELECT 1 FROM publications WHERE id = :id"), {"id": kept}
        ).scalar_one_or_none()
        assert still_there == 1

    def test_limit_caps_batch(self, sa_sync_conn):
        # On vide d'abord les orphelines existantes (rollback en fin de test) pour
        # un compte déterministe, puis on batche 3 nouvelles par chunks de 2.
        _Q.purge_orphan_publications(sa_sync_conn)
        for title in ("a", "b", "c"):
            insert_publication(sa_sync_conn, title)
        assert _Q.purge_orphan_publications(sa_sync_conn, limit=2) == 2
        assert _Q.purge_orphan_publications(sa_sync_conn, limit=2) == 1
        assert _Q.purge_orphan_publications(sa_sync_conn, limit=2) == 0

    def test_cascades_publication_subjects(self, sa_sync_conn):
        # Les sujets d'une orpheline disparaissent par CASCADE : c'est ce qui
        # garde `publication_subjects` scopé périmètre sans filtre dans subjects.
        orphan = insert_publication(sa_sync_conn, "orphan")
        s_id = insert_subject(sa_sync_conn, "vaches laitieres")
        insert_publication_subject(sa_sync_conn, orphan, subject_id=s_id)
        _Q.purge_orphan_publications(sa_sync_conn)
        n_links = sa_sync_conn.execute(
            text("SELECT count(*) FROM publication_subjects WHERE publication_id = :p"),
            {"p": orphan},
        ).scalar_one()
        assert n_links == 0
