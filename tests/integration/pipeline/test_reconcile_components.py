"""Intégration : passe de réconciliation des composantes (merge-only).

Valide le SQL neuf (voisinage 1-hop, fetch dirty, clear) sur vraie base, et le bout-en-bout `run()` (fusion + nettoyage du drapeau) — `conn.commit` neutralisé pour rester dans la transaction rollbackée.
"""

import logging

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import JSONB

from application.pipeline.publications.reconcile_components import reconcile, run
from domain.source_publications.keys import project_confirmation_keys
from infrastructure.queries.pipeline.publications_reconciliation import (
    PgPublicationsReconciliationQueries,
    fetch_dirty_source_publication_ids,
    fetch_reconciliation_universe,
    mark_keys_dirty,
)
from infrastructure.repositories import publication_repository
from tests.integration.helpers.authorships import upsert_identity

logger = logging.getLogger("test_reconcile_components")


def _seed_pub(conn, doi=None) -> int:
    return publication_repository(conn).create(
        title="T",
        title_normalized="t",
        doc_type="article",
        pub_year=2024,
        doi=doi,
        oa_status="unknown",
    )


def _seed_sp(
    conn,
    *,
    source_id,
    publication_id=None,
    doi=None,
    external_ids=None,
    keys_dirty=True,
    doc_type="article",
    title_normalized=None,
):
    stmt = text("""
        INSERT INTO source_publications
            (source, source_id, title, title_normalized, pub_year, doc_type, doi, external_ids,
             publication_id, keys_dirty)
        VALUES ('openalex', :sid, 'T', :tn, 2024, :dt, :doi, :ext, :pid, :dirty)
        RETURNING id
    """).bindparams(bindparam("ext", type_=JSONB))
    return conn.execute(
        stmt,
        {
            "sid": source_id,
            "tn": title_normalized,
            "dt": doc_type,
            "doi": doi,
            "ext": external_ids or {},
            "pid": publication_id,
            "dirty": keys_dirty,
        },
    ).scalar_one()


def _pub_exists(conn, pub_id) -> bool:
    return (
        conn.execute(text("SELECT 1 FROM publications WHERE id = :id"), {"id": pub_id}).first()
        is not None
    )


def _sp_state(conn, sp_id) -> tuple:
    return conn.execute(
        text("SELECT publication_id, keys_dirty FROM source_publications WHERE id = :id"),
        {"id": sp_id},
    ).one()


class TestUniverse:
    def test_fetches_dirty_and_one_hop_neighbor(self, sa_sync_conn):
        """Le voisinage = SP dirty + SP non-dirty partageant une clé ; ignore les non-liées.

        DOI porté par les SP, pas par les publications (`UNIQUE(lower(doi))` interdit deux pubs
        au même DOI) ; le voisinage par DOI joint sur `source_publications.doi`."""
        conn = sa_sync_conn
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        unrelated_pub = _seed_pub(conn)
        dirty = _seed_sp(conn, source_id="a", publication_id=pub_a, doi="10.1/x", keys_dirty=True)
        neighbor = _seed_sp(
            conn, source_id="b", publication_id=pub_b, doi="10.1/x", keys_dirty=False
        )
        _seed_sp(conn, source_id="c", publication_id=unrelated_pub, doi="10.9/z", keys_dirty=False)

        universe = {r.id for r in fetch_reconciliation_universe(conn)}
        assert universe == {dirty, neighbor}

    def test_neighbor_by_hal_id(self, sa_sync_conn):
        conn = sa_sync_conn
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        dirty = _seed_sp(
            conn, source_id="a", publication_id=pub_a, external_ids={"hal_id": ["hal-1"]}
        )
        neighbor = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            external_ids={"hal_id": ["hal-1", "hal-2"]},
            keys_dirty=False,
        )
        assert {r.id for r in fetch_reconciliation_universe(conn)} == {dirty, neighbor}

    def test_neighbor_by_metadata_block(self, sa_sync_conn):
        """Voisinage par token bloc métadonnée : deux SP de même doc_type + titre (long) + année, sans clé d'identifiant partagée (ici des thèses)."""
        conn = sa_sync_conn
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        dirty = _seed_sp(
            conn,
            source_id="a",
            publication_id=pub_a,
            doc_type="thesis",
            title_normalized="ma these de doctorat au titre suffisamment long",
        )
        neighbor = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            doc_type="thesis",
            title_normalized="ma these de doctorat au titre suffisamment long",
            keys_dirty=False,
        )
        assert {r.id for r in fetch_reconciliation_universe(conn)} == {dirty, neighbor}

    def test_dirty_orphan_included(self, sa_sync_conn):
        """Une SP orpheline dirty EST un seed : l'assignation est unifiée dans la réconciliation
        (elle se fait matcher / créer / skipper par le même primitif)."""
        conn = sa_sync_conn
        orphan = _seed_sp(
            conn, source_id="orphan", publication_id=None, doi="10.1/x", keys_dirty=True
        )
        assert fetch_dirty_source_publication_ids(conn) == [orphan]


class TestEndToEnd:
    def test_two_pubs_sharing_doi_merged(self, sa_sync_conn, monkeypatch):
        """Deux pubs dont les SP partagent un DOI → fusion. Les pubs n'ont pas (encore) le DOI en
        colonne (`UNIQUE(lower(doi))` interdit deux pubs au même DOI) : aucune ne le porte, donc
        l'ancre tombe sur le `min(source_publication_id)`."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        sp_a = _seed_sp(conn, source_id="a", publication_id=pub_a, doi="10.1/x")
        sp_b = _seed_sp(conn, source_id="b", publication_id=pub_b, doi="10.1/x")

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            publication_repo=publication_repository(conn),
        )

        # Aucune pub ne porte le DOI en colonne → ancre = pub du plus petit source_publication_id.
        anchor, absorbed = (pub_a, pub_b) if sp_a < sp_b else (pub_b, pub_a)
        assert _pub_exists(conn, anchor)
        assert not _pub_exists(conn, absorbed)
        assert _sp_state(conn, sp_a) == (anchor, False)
        assert _sp_state(conn, sp_b) == (anchor, False)

    def test_pub_with_two_dois_splits(self, sa_sync_conn, monkeypatch):
        """Une pub portant doi=X héberge une SP doi=Y (reliées par hal_id) → X garde la pub,
        Y part sur un nouveau pub."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub = _seed_pub(conn, doi="10.1/x")
        sp_x = _seed_sp(
            conn, source_id="x", publication_id=pub, doi="10.1/x", external_ids={"hal_id": ["h"]}
        )
        sp_y = _seed_sp(
            conn, source_id="y", publication_id=pub, doi="10.2/y", external_ids={"hal_id": ["h"]}
        )

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            publication_repo=publication_repository(conn),
        )

        # X garde le pub d'origine ; Y est parti sur un autre pub (créé).
        assert _sp_state(conn, sp_x) == (pub, False)
        y_pub, y_dirty = _sp_state(conn, sp_y)
        assert y_pub != pub
        assert y_dirty is False
        assert _pub_exists(conn, pub)
        assert _pub_exists(conn, y_pub)

    def test_two_theses_sharing_title_year_merged(self, sa_sync_conn, monkeypatch):
        """Deux thèses cross-source, même titre (long) + année, sans DOI/NNT/hal partagé → fusion par token bloc métadonnée."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        sp_a = _seed_sp(
            conn,
            source_id="a",
            publication_id=pub_a,
            doc_type="thesis",
            title_normalized="ma these de doctorat au titre suffisamment long",
        )
        sp_b = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            doc_type="thesis",
            title_normalized="ma these de doctorat au titre suffisamment long",
        )

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            publication_repo=publication_repository(conn),
        )

        anchor, absorbed = (pub_a, pub_b) if sp_a < sp_b else (pub_b, pub_a)
        assert _pub_exists(conn, anchor)
        assert not _pub_exists(conn, absorbed)
        assert _sp_state(conn, sp_a) == (anchor, False)
        assert _sp_state(conn, sp_b) == (anchor, False)

    def test_distinct_dois_not_merged(self, sa_sync_conn, monkeypatch):
        """Deux pubs à DOI distincts partageant un hal_id : pas de fusion (cannot-link DOI)."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn, doi="10.1/x")
        pub_b = _seed_pub(conn, doi="10.2/y")
        sp_a = _seed_sp(
            conn,
            source_id="a",
            publication_id=pub_a,
            doi="10.1/x",
            external_ids={"hal_id": ["hal-1"]},
        )
        sp_b = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            doi="10.2/y",
            external_ids={"hal_id": ["hal-1"]},
        )

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            publication_repo=publication_repository(conn),
        )

        assert _pub_exists(conn, pub_a)
        assert _pub_exists(conn, pub_b)
        # Drapeaux nettoyés malgré l'absence de fusion (les SP ont été réconciliées).
        assert _sp_state(conn, sp_a)[1] is False
        assert _sp_state(conn, sp_b)[1] is False


class TestMetadataBlock:
    LONG = "une communication scientifique au titre assez long"

    def test_two_conference_papers_merged(self, sa_sync_conn, monkeypatch):
        """Deux conference_paper cross-source, même titre (long) + année, sans DOI → fusion par token bloc."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        sp_a = _seed_sp(
            conn,
            source_id="a",
            publication_id=pub_a,
            doc_type="conference_paper",
            title_normalized=self.LONG,
        )
        sp_b = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            doc_type="conference_paper",
            title_normalized=self.LONG,
        )

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            publication_repo=publication_repository(conn),
        )

        anchor, absorbed = (pub_a, pub_b) if sp_a < sp_b else (pub_b, pub_a)
        assert _pub_exists(conn, anchor)
        assert not _pub_exists(conn, absorbed)
        assert _sp_state(conn, sp_a) == (anchor, False)
        assert _sp_state(conn, sp_b) == (anchor, False)

    def test_short_title_not_merged(self, sa_sync_conn, monkeypatch):
        """Titre court (≤ seuil) → pas de token bloc, pas de fusion (garde de longueur)."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        sp_a = _seed_sp(
            conn,
            source_id="a",
            publication_id=pub_a,
            doc_type="conference_paper",
            title_normalized="court titre",
        )
        sp_b = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            doc_type="conference_paper",
            title_normalized="court titre",
        )

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            publication_repo=publication_repository(conn),
        )

        assert _pub_exists(conn, pub_a)
        assert _pub_exists(conn, pub_b)
        assert _sp_state(conn, sp_a)[1] is False
        assert _sp_state(conn, sp_b)[1] is False

    def test_different_doc_type_not_merged(self, sa_sync_conn, monkeypatch):
        """Même titre long + année mais doc_type différents → pas de fusion (doc_type dans la clé)."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        sp_a = _seed_sp(
            conn,
            source_id="a",
            publication_id=pub_a,
            doc_type="conference_paper",
            title_normalized=self.LONG,
        )
        sp_b = _seed_sp(
            conn,
            source_id="b",
            publication_id=pub_b,
            doc_type="book_chapter",
            title_normalized=self.LONG,
        )

        run(
            conn,
            PgPublicationsReconciliationQueries(),
            logger,
            publication_repo=publication_repository(conn),
        )

        assert _pub_exists(conn, pub_a)
        assert _pub_exists(conn, pub_b)
        assert _sp_state(conn, sp_a)[1] is False
        assert _sp_state(conn, sp_b)[1] is False


class TestMarkKeysDirty:
    """Primitive de re-matérialisation : re-dirty total ou ciblé (CLI maintenance + flag rebuild)."""

    def test_mark_all(self, sa_sync_conn):
        conn = sa_sync_conn
        a = _seed_sp(conn, source_id="a", keys_dirty=False, doc_type="article")
        b = _seed_sp(conn, source_id="b", keys_dirty=False, doc_type="book_chapter")
        assert mark_keys_dirty(conn) >= 2
        assert _sp_state(conn, a)[1] is True
        assert _sp_state(conn, b)[1] is True

    def test_mark_where_targets_subset(self, sa_sync_conn):
        conn = sa_sync_conn
        art = _seed_sp(conn, source_id="art", keys_dirty=False, doc_type="article")
        chap = _seed_sp(conn, source_id="chap", keys_dirty=False, doc_type="book_chapter")
        mark_keys_dirty(conn, "doc_type = 'book_chapter'")
        assert _sp_state(conn, chap)[1] is True
        assert _sp_state(conn, art)[1] is False

    def test_dry_run_counts_without_writing(self, sa_sync_conn):
        conn = sa_sync_conn
        sp = _seed_sp(conn, source_id="d", keys_dirty=False, doc_type="poster")
        assert mark_keys_dirty(conn, "doc_type = 'poster'", dry_run=True) >= 1
        assert _sp_state(conn, sp)[1] is False  # dry-run n'écrit pas


class TestUniverseMatchesPythonTokens:
    """Différentiel anti-divergence : le voisinage SQL (branches d'univers) relie exactement les
    SP que les tokens Python (`project_confirmation_keys`) relient. Les deux encodages du même
    critère d'égalité doivent s'accorder — surtout la garde de longueur `metadata_block`.

    Pour chaque SP, on la marque seule dirty et on compare son voisinage 1-hop SQL à l'ensemble
    des SP dont les tokens Python intersectent les siens.
    """

    def test_sql_universe_matches_python_token_linkage(self, sa_sync_conn):
        conn = sa_sync_conn
        long_a, long_b = "a" * 40, "b" * 40
        len30 = "c" * 30  # juste SOUS le seuil strict > 30 → pas de token metadata_block
        ids = [
            _seed_sp(conn, source_id="doi1", doi="10.1/x", keys_dirty=False),
            _seed_sp(conn, source_id="doi2", doi="10.1/x", keys_dirty=False),
            _seed_sp(
                conn,
                source_id="hal1",
                external_ids={"hal_id": ["hal-00000001", "hal-00000002"]},
                keys_dirty=False,
            ),
            _seed_sp(
                conn,
                source_id="hal2",
                external_ids={"hal_id": ["hal-00000002", "hal-00000003"]},
                keys_dirty=False,
            ),
            # Préfixe de collection institutionnelle : le VO HALId doit l'accepter comme token
            # (sinon le SQL les rapproche mais le clustering Python non → divergence + non-fusion).
            # Le numéro fait 8 chiffres (docid CCSD), exigence du VO.
            _seed_sp(
                conn,
                source_id="emse1",
                external_ids={"hal_id": ["emse-04836977"]},
                keys_dirty=False,
            ),
            _seed_sp(
                conn,
                source_id="emse2",
                external_ids={"hal_id": ["emse-04836977"]},
                keys_dirty=False,
            ),
            _seed_sp(conn, source_id="nnt1", external_ids={"nnt": "2024UCA01"}, keys_dirty=False),
            _seed_sp(conn, source_id="nnt2", external_ids={"nnt": "2024UCA01"}, keys_dirty=False),
            _seed_sp(
                conn,
                source_id="mb1",
                doc_type="conference_paper",
                title_normalized=long_a,
                keys_dirty=False,
            ),
            _seed_sp(
                conn,
                source_id="mb2",
                doc_type="conference_paper",
                title_normalized=long_a,
                keys_dirty=False,
            ),
            _seed_sp(
                conn,
                source_id="mbo",
                doc_type="conference_paper",
                title_normalized=long_b,
                keys_dirty=False,
            ),
            _seed_sp(
                conn, source_id="s1", doc_type="article", title_normalized=len30, keys_dirty=False
            ),
            _seed_sp(
                conn, source_id="s2", doc_type="article", title_normalized=len30, keys_dirty=False
            ),
            _seed_sp(
                conn, source_id="lone", doc_type="article", title_normalized="zz", keys_dirty=False
            ),
        ]
        rows = {
            r.id: r
            for r in conn.execute(
                text(
                    "SELECT id, doi, external_ids, doc_type, title_normalized, pub_year "
                    "FROM source_publications WHERE id = ANY(:ids)"
                ).bindparams(bindparam("ids")),
                {"ids": ids},
            )
        }
        toks = {
            i: project_confirmation_keys(
                r.doi, r.external_ids, r.doc_type, r.title_normalized, r.pub_year
            ).tokens()
            for i, r in rows.items()
        }
        seeded = set(ids)
        for i in ids:
            conn.execute(
                text(
                    "UPDATE source_publications SET keys_dirty = (id = :i) WHERE id = ANY(:ids)"
                ).bindparams(bindparam("ids")),
                {"i": i, "ids": ids},
            )
            sql_neighbors = {r.id for r in fetch_reconciliation_universe(conn)} & seeded - {i}
            py_neighbors = {j for j in ids if j != i and toks[i] & toks[j]}
            assert sql_neighbors == py_neighbors, (
                f"divergence SP {i} : SQL={sql_neighbors} Python={py_neighbors}"
            )


class TestExternalDoiCarrier:
    """Régression : une publication orpheline (sans SP) portant un DOI — état typique après un
    TRUNCATE + réimport des sources — ne doit pas faire planter la réconciliation. Les SP fraîches
    portant ce DOI s'y rattachent au lieu de créer une pub neuve (qui violerait l'unicité du DOI)."""

    def test_orphan_publication_with_doi_is_reused_not_duplicated(self, sa_sync_conn):
        conn = sa_sync_conn
        orphan_pub = _seed_pub(conn, doi="10.70675/abc")  # porte le DOI, aucune SP
        sp1 = _seed_sp(
            conn, source_id="t1", doi="10.70675/abc", title_normalized="t", keys_dirty=True
        )
        sp2 = _seed_sp(conn, source_id="t2", doi="10.70675/abc", keys_dirty=True)
        # in_perimeter → sans le correctif, ce groupe d'orphelins serait une CRÉATION et
        # planterait sur publications_doi_lower_key ; avec, il s'ancre sur la pub existante.
        conn.execute(
            text(
                "INSERT INTO source_authorships (source, source_publication_id, in_perimeter, identity_id) "
                "VALUES ('openalex', :sp, true, :iid)"
            ),
            {"sp": sp1, "iid": upsert_identity(conn)},
        )

        reconcile(
            conn,
            PgPublicationsReconciliationQueries(),
            publication_repo=publication_repository(conn),
        )

        assert _pub_exists(conn, orphan_pub)
        assert _sp_state(conn, sp1)[0] == orphan_pub
        assert _sp_state(conn, sp2)[0] == orphan_pub
        n = conn.execute(
            text("SELECT count(*) FROM publications WHERE lower(doi) = '10.70675/abc'")
        ).scalar_one()
        assert n == 1
