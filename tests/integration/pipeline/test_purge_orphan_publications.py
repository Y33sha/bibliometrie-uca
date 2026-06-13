"""Tests d'intégration de la purge des publications orphelines (zéro authorship).

Garde principale : une publication AVEC authorship n'est jamais supprimée (la
purge ne doit toucher que les orphelines hors-périmètre). Et la cascade
`publication_subjects` confirme que cette table reste scopée périmètre sans
filtre propre.
"""

from sqlalchemy import text

from infrastructure.queries.pipeline.purge_orphan_publications import (
    purge_orphan_publications,
)


def _create_pub(conn, title="X"):
    return conn.execute(
        text(
            "INSERT INTO publications (title, pub_year, doc_type) "
            "VALUES (:t, 2024, 'article') RETURNING id"
        ),
        {"t": title},
    ).scalar_one()


def _create_person(conn):
    return conn.execute(
        text(
            "INSERT INTO persons "
            "(last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES ('Doe', 'Jane', 'doe', 'jane') RETURNING id"
        )
    ).scalar_one()


def _add_authorship(conn, *, pub_id, person_id):
    conn.execute(
        text("INSERT INTO authorships (publication_id, person_id) VALUES (:p, :pe)"),
        {"p": pub_id, "pe": person_id},
    )


class TestPurgeOrphanPublications:
    def test_deletes_pub_without_authorship(self, sa_sync_conn):
        orphan = _create_pub(sa_sync_conn, "orphan")
        purge_orphan_publications(sa_sync_conn)
        still_there = sa_sync_conn.execute(
            text("SELECT 1 FROM publications WHERE id = :id"), {"id": orphan}
        ).scalar_one_or_none()
        assert still_there is None

    def test_keeps_pub_with_authorship(self, sa_sync_conn):
        kept = _create_pub(sa_sync_conn, "kept")
        person = _create_person(sa_sync_conn)
        _add_authorship(sa_sync_conn, pub_id=kept, person_id=person)
        purge_orphan_publications(sa_sync_conn)
        still_there = sa_sync_conn.execute(
            text("SELECT 1 FROM publications WHERE id = :id"), {"id": kept}
        ).scalar_one_or_none()
        assert still_there == 1

    def test_limit_caps_batch(self, sa_sync_conn):
        # On vide d'abord les orphelines existantes (rollback en fin de test) pour
        # un compte déterministe, puis on batche 3 nouvelles par chunks de 2.
        purge_orphan_publications(sa_sync_conn)
        for title in ("a", "b", "c"):
            _create_pub(sa_sync_conn, title)
        assert purge_orphan_publications(sa_sync_conn, limit=2) == 2
        assert purge_orphan_publications(sa_sync_conn, limit=2) == 1
        assert purge_orphan_publications(sa_sync_conn, limit=2) == 0

    def test_cascades_publication_subjects(self, sa_sync_conn):
        # Les sujets d'une orpheline disparaissent par CASCADE : c'est ce qui
        # garde `publication_subjects` scopé périmètre sans filtre dans subjects.
        orphan = _create_pub(sa_sync_conn, "orphan")
        s_id = sa_sync_conn.execute(
            text("INSERT INTO subjects (label) VALUES ('vaches laitieres') RETURNING id")
        ).scalar_one()
        sa_sync_conn.execute(
            text(
                "INSERT INTO publication_subjects (publication_id, subject_id, source) "
                "VALUES (:p, :s, 'hal')"
            ),
            {"p": orphan, "s": s_id},
        )
        purge_orphan_publications(sa_sync_conn)
        n_links = sa_sync_conn.execute(
            text("SELECT count(*) FROM publication_subjects WHERE publication_id = :p"),
            {"p": orphan},
        ).scalar_one()
        assert n_links == 0
