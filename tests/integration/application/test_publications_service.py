"""Tests d'intégration pour application/services/publications/core.py.

Couvre `merge_publications` (garde DOI, transfert des dépendants, recompute des
métadonnées canoniques depuis les sources) et `mark_distinct`.

Une publication n'existe qu'attestée par au moins une `source_publication` : les
helpers sèment donc toujours la ligne `publications` **et** une SP rattachée qui
porte les mêmes métadonnées. C'est cette SP qui fait exister la publication, et
`merge_publications` recompute le canonique depuis l'union des SP.
"""

import pytest
from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.services.publications.core import mark_distinct, merge_publications
from domain.errors import DistinctDoiError, NotFoundError, ValidationError
from infrastructure.repositories import publication_repository


@pytest.fixture
def repo(sa_sync_conn):
    return publication_repository(sa_sync_conn)


# ── Helpers ────────────────────────────────────────────────────────


def _insert_journal(conn, title="Nature"):
    return conn.execute(
        text("INSERT INTO journals (title, title_normalized) VALUES (:t, lower(:t)) RETURNING id"),
        {"t": title},
    ).scalar_one()


def _insert_publication(
    conn,
    title="Test",
    pub_year=2024,
    doi=None,
    doc_type="article",
    journal_id=None,
    oa_status="unknown",
):
    """Insère une ligne `publications` brute (sans source rattachée). Réservé à
    `_seed_publication` : une publication sans SP est un état interdit, jamais un
    point de départ de test."""
    return conn.execute(
        text(
            """
            INSERT INTO publications (title, title_normalized, pub_year, doi,
                                      doc_type, journal_id, oa_status)
            VALUES (:title, lower(:title), :pub_year, :doi,
                    CAST(:doc_type AS doc_type), :journal_id, CAST(:oa_status AS oa_type))
            RETURNING id
            """
        ),
        {
            "title": title,
            "pub_year": pub_year,
            "doi": doi,
            "doc_type": doc_type,
            "journal_id": journal_id,
            "oa_status": oa_status,
        },
    ).scalar_one()


_INSERT_SOURCE_PUB_SQL = text(
    """
    INSERT INTO source_publications (source, source_id, title, pub_year, publication_id,
                                     doi, doc_type, oa_status, journal_id, language, external_ids)
    VALUES (:source, :source_id, :title, :pub_year, :publication_id,
            :doi, :doc_type, :oa_status, :journal_id, :language, :external_ids)
    RETURNING id
    """
).bindparams(bindparam("external_ids", type_=JSONB))


def _insert_source_publication(
    conn,
    publication_id,
    source="hal",
    source_id="h-1",
    title="Test",
    pub_year=2024,
    doi=None,
    doc_type="article",
    oa_status=None,
    journal_id=None,
    language=None,
    external_ids=None,
):
    return conn.execute(
        _INSERT_SOURCE_PUB_SQL,
        {
            "source": source,
            "source_id": source_id,
            "title": title,
            "pub_year": pub_year,
            "publication_id": publication_id,
            "doi": doi,
            "doc_type": doc_type,
            "oa_status": oa_status,
            "journal_id": journal_id,
            "language": language,
            "external_ids": external_ids or {},
        },
    ).scalar_one()


def _seed_publication(
    conn,
    title="Test",
    pub_year=2024,
    doi=None,
    doc_type="article",
    journal_id=None,
    oa_status="unknown",
    language=None,
    source="hal",
    source_id=None,
):
    """Sème une publication valide : la ligne `publications` et une `source_publication`
    rattachée qui porte les mêmes métadonnées. Retourne l'id de la publication."""
    pub_id = _insert_publication(
        conn,
        title=title,
        pub_year=pub_year,
        doi=doi,
        doc_type=doc_type,
        journal_id=journal_id,
        oa_status=oa_status,
    )
    _insert_source_publication(
        conn,
        pub_id,
        source=source,
        source_id=source_id or f"{source}-{pub_id}",
        title=title,
        pub_year=pub_year,
        doi=doi,
        doc_type=doc_type,
        oa_status=oa_status,
        journal_id=journal_id,
        language=language,
    )
    return pub_id


def _insert_person(conn, last="Dupont", first="Jean"):
    return conn.execute(
        text(
            """
            INSERT INTO persons (last_name, first_name,
                                 last_name_normalized, first_name_normalized)
            VALUES (:last, :first, lower(:last), lower(:first)) RETURNING id
            """
        ),
        {"last": last, "first": first},
    ).scalar_one()


def _insert_authorship(conn, publication_id, person_id=None):
    return conn.execute(
        text(
            "INSERT INTO authorships (publication_id, person_id) "
            "VALUES (:pid, :person_id) RETURNING id"
        ),
        {"pid": publication_id, "person_id": person_id},
    ).scalar_one()


def _select_one(conn, sql, **binds):
    return conn.execute(text(sql), binds).one_or_none()


def _oa_status(conn, pub_id):
    return conn.execute(
        text("SELECT oa_status FROM publications WHERE id = :id"), {"id": pub_id}
    ).scalar_one()


# ── merge_publications ────────────────────────────────────────────


class TestMergePublications:
    def test_raises_on_self_merge(self, sa_sync_conn, repo):
        pub = _seed_publication(sa_sync_conn, title="Seule", source_id="h-self")
        with pytest.raises(ValidationError, match="elle-même"):
            merge_publications(pub, pub, repo=repo)

    def test_raises_not_found(self, sa_sync_conn, repo):
        pub = _seed_publication(sa_sync_conn, title="Seule", source_id="h-nf")
        with pytest.raises(NotFoundError):
            merge_publications(pub, 999999, repo=repo)

    def test_transfers_source_publications_and_authorships(self, sa_sync_conn, repo):
        target = _seed_publication(sa_sync_conn, title="Target", source_id="h-tgt")
        source = _seed_publication(sa_sync_conn, title="Source", source_id="h-src")
        person_id = _insert_person(sa_sync_conn)
        auth_id = _insert_authorship(sa_sync_conn, source, person_id=person_id)

        merge_publications(target, source, repo=repo)

        # source_publication de la source repointée vers la cible
        sp_pub = sa_sync_conn.execute(
            text("SELECT publication_id FROM source_publications WHERE source_id = 'h-src'")
        ).scalar_one()
        assert sp_pub == target
        # authorship repointée
        auth_pub = sa_sync_conn.execute(
            text("SELECT publication_id FROM authorships WHERE id = :id"), {"id": auth_id}
        ).scalar_one()
        assert auth_pub == target
        # source supprimée
        assert (
            _select_one(sa_sync_conn, "SELECT id FROM publications WHERE id = :id", id=source)
            is None
        )
        # cible survivante (elle porte des SP)
        assert (
            _select_one(sa_sync_conn, "SELECT id FROM publications WHERE id = :id", id=target)
            is not None
        )

    def test_refuses_distinct_dois(self, sa_sync_conn, repo):
        """Garde « 1 DOI = 1 publication » : deux DOI non-nuls différents → refus,
        aucune des deux n'est touchée."""
        target = _seed_publication(sa_sync_conn, doi="10.1/a", source_id="h-tgt")
        source = _seed_publication(sa_sync_conn, doi="10.2/b", source_id="h-src")
        with pytest.raises(DistinctDoiError):
            merge_publications(target, source, repo=repo)
        for pid in (target, source):
            assert (
                _select_one(sa_sync_conn, "SELECT id FROM publications WHERE id = :id", id=pid)
                is not None
            )

    def test_merges_when_one_doi_null(self, sa_sync_conn, repo):
        """Un seul DOI non-null : pas de conflit, fusion appliquée ; la cible garde son DOI."""
        target = _seed_publication(sa_sync_conn, doi="10.1/a", source_id="h-tgt")
        source = _seed_publication(sa_sync_conn, doi=None, source_id="h-src")
        merge_publications(target, source, repo=repo)
        assert (
            _select_one(sa_sync_conn, "SELECT id FROM publications WHERE id = :id", id=source)
            is None
        )
        doi = sa_sync_conn.execute(
            text("SELECT doi FROM publications WHERE id = :id"), {"id": target}
        ).scalar_one()
        assert doi == "10.1/a"

    def test_dedup_authorships_by_person(self, sa_sync_conn, repo):
        """Si target et source ont une authorship pour la même personne, celle de la source est jetée."""
        target = _seed_publication(sa_sync_conn, title="Target", source_id="h-tgt")
        source = _seed_publication(sa_sync_conn, title="Source", source_id="h-src")
        person_id = _insert_person(sa_sync_conn)
        keep_auth = _insert_authorship(sa_sync_conn, target, person_id=person_id)
        drop_auth = _insert_authorship(sa_sync_conn, source, person_id=person_id)

        merge_publications(target, source, repo=repo)

        assert (
            _select_one(sa_sync_conn, "SELECT id FROM authorships WHERE id = :id", id=keep_auth)
            is not None
        )
        assert (
            _select_one(sa_sync_conn, "SELECT id FROM authorships WHERE id = :id", id=drop_auth)
            is None
        )

    def test_recomputes_journal_id_from_sources(self, sa_sync_conn, repo):
        """La cible sans journal reçoit celui de la source par recompute (premier non-nul)."""
        j_id = _insert_journal(sa_sync_conn)
        target = _seed_publication(sa_sync_conn, title="Target", journal_id=None, source_id="h-tgt")
        source = _seed_publication(sa_sync_conn, title="Source", journal_id=j_id, source_id="h-src")

        merge_publications(target, source, repo=repo)

        result = sa_sync_conn.execute(
            text("SELECT journal_id FROM publications WHERE id = :id"), {"id": target}
        ).scalar_one()
        assert result == j_id

    def test_recomputes_doi_when_target_has_none(self, sa_sync_conn, repo):
        """Cible sans DOI, source avec : le recompute promeut le DOI de la source."""
        target = _seed_publication(sa_sync_conn, title="Target", doi=None, source_id="h-tgt")
        source = _seed_publication(
            sa_sync_conn, title="Source", doi="10.1234/src", source_id="h-src"
        )

        merge_publications(target, source, repo=repo)

        doi = sa_sync_conn.execute(
            text("SELECT doi FROM publications WHERE id = :id"), {"id": target}
        ).scalar_one()
        assert doi == "10.1234/src"

    def test_recomputes_oa_status_diamond_wins(self, sa_sync_conn, repo):
        """Statut OA le plus ouvert : une source diamond fait passer la cible en diamond."""
        target = _seed_publication(
            sa_sync_conn, title="Target", oa_status="gold", source_id="h-tgt"
        )
        source = _seed_publication(
            sa_sync_conn, title="Source", oa_status="diamond", source_id="h-src"
        )
        merge_publications(target, source, repo=repo)
        assert _oa_status(sa_sync_conn, target) == "diamond"

    def test_recomputes_oa_status_from_closed_to_gold(self, sa_sync_conn, repo):
        target = _seed_publication(
            sa_sync_conn, title="Target", oa_status="closed", source_id="h-tgt"
        )
        source = _seed_publication(
            sa_sync_conn, title="Source", oa_status="gold", source_id="h-src"
        )
        merge_publications(target, source, repo=repo)
        assert _oa_status(sa_sync_conn, target) == "gold"


class TestMarkDistinct:
    def test_raises_on_same_id(self, sa_sync_conn, repo):
        pub = _seed_publication(sa_sync_conn, title="Seule", source_id="h-md")
        with pytest.raises(ValidationError, match="elle-même"):
            mark_distinct(pub, pub, repo=repo)

    def test_inserts_ordered_pair(self, sa_sync_conn, repo):
        p1 = _seed_publication(sa_sync_conn, title="A", source_id="h-a")
        p2 = _seed_publication(sa_sync_conn, title="B", source_id="h-b")
        mark_distinct(p2, p1, repo=repo)  # ordre inverse exprès
        assert (
            _select_one(
                sa_sync_conn,
                "SELECT pub_id_a, pub_id_b FROM distinct_publications "
                "WHERE pub_id_a = :a AND pub_id_b = :b",
                a=min(p1, p2),
                b=max(p1, p2),
            )
            is not None
        )

    def test_idempotent(self, sa_sync_conn, repo):
        p1 = _seed_publication(sa_sync_conn, title="A", source_id="h-a")
        p2 = _seed_publication(sa_sync_conn, title="B", source_id="h-b")
        mark_distinct(p1, p2, repo=repo)
        mark_distinct(p1, p2, repo=repo)  # ON CONFLICT DO NOTHING
        n = sa_sync_conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM distinct_publications "
                "WHERE pub_id_a = :a AND pub_id_b = :b"
            ),
            {"a": min(p1, p2), "b": max(p1, p2)},
        ).scalar_one()
        assert n == 1


class TestMergeRepointsDistinct:
    """Une fusion repointe les paires `distinct_publications` du perdant vers le
    gagnant (au lieu de les supprimer) : la distinction survit à la fusion."""

    @staticmethod
    def _pairs(conn) -> set[tuple[int, int]]:
        return {
            (r.pub_id_a, r.pub_id_b)
            for r in conn.execute(
                text("SELECT pub_id_a, pub_id_b FROM distinct_publications")
            ).all()
        }

    def test_repoints_loser_to_winner(self, sa_sync_conn, repo):
        winner = _seed_publication(sa_sync_conn, title="Winner", source_id="h-win")
        loser = _seed_publication(sa_sync_conn, title="Loser", source_id="h-lose")
        other = _seed_publication(sa_sync_conn, title="Other", source_id="h-other")
        mark_distinct(loser, other, repo=repo)  # (loser, other) distinctes

        merge_publications(winner, loser, repo=repo)  # loser absorbée par winner

        pairs = self._pairs(sa_sync_conn)
        assert (min(winner, other), max(winner, other)) in pairs
        assert all(loser not in pair for pair in pairs)  # plus de référence au perdant

    def test_dedupes_when_target_pair_exists(self, sa_sync_conn, repo):
        winner = _seed_publication(sa_sync_conn, title="Winner", source_id="h-win")
        loser = _seed_publication(sa_sync_conn, title="Loser", source_id="h-lose")
        other = _seed_publication(sa_sync_conn, title="Other", source_id="h-other")
        mark_distinct(loser, other, repo=repo)
        mark_distinct(winner, other, repo=repo)  # la paire cible existe déjà

        merge_publications(winner, loser, repo=repo)

        n = sa_sync_conn.execute(
            text(
                "SELECT COUNT(*) AS n FROM distinct_publications "
                "WHERE pub_id_a = :a AND pub_id_b = :b"
            ),
            {"a": min(winner, other), "b": max(winner, other)},
        ).scalar_one()
        assert n == 1  # ON CONFLICT DO NOTHING : pas de doublon

    def test_drops_self_pair(self, sa_sync_conn, repo):
        """Défensif : si perdant et gagnant étaient marqués distincts, la fusion
        ne crée pas d'auto-paire (gagnant, gagnant)."""
        winner = _seed_publication(sa_sync_conn, title="Winner", source_id="h-win")
        loser = _seed_publication(sa_sync_conn, title="Loser", source_id="h-lose")
        mark_distinct(winner, loser, repo=repo)

        merge_publications(winner, loser, repo=repo)

        assert all(winner not in pair for pair in self._pairs(sa_sync_conn))
