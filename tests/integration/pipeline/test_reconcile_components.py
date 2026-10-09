"""Intégration : passe de réconciliation des composantes (merge-only).

Valide le SQL neuf (voisinage 1-hop, fetch dirty, clear) sur vraie base, et le bout-en-bout `run()` (fusion + nettoyage du drapeau) — `conn.commit` neutralisé pour rester dans la transaction rollbackée.
"""

import logging

from sqlalchemy import bindparam, text

from application.pipeline.publications.reconcile_components import reconcile, run
from domain.source_publications.keys import project_confirmation_keys
from infrastructure.pipeline.publications.reconciliation import (
    PgPublicationsReconciliationQueries,
    mark_keys_dirty,
)

_Q = PgPublicationsReconciliationQueries()
from infrastructure.repositories import publication_repository
from tests.integration.helpers.authorships import upsert_identity
from tests.integration.helpers.sources import insert_source_publication

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
        dirty = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
        )
        neighbor = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
        )
        insert_source_publication(
            conn,
            unrelated_pub,
            source="openalex",
            source_id="c",
            title="T",
            doi="10.9/z",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
        )

        universe = {r.id for r in _Q.fetch_reconciliation_universe(conn)}
        assert universe == {dirty, neighbor}

    def test_neighbor_by_hal_id(self, sa_sync_conn):
        conn = sa_sync_conn
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        dirty = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            pub_year=2024,
            doc_type="article",
            external_ids={"hal_id": ["hal-1"]},
        )
        neighbor = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
            external_ids={"hal_id": ["hal-1", "hal-2"]},
        )
        assert {r.id for r in _Q.fetch_reconciliation_universe(conn)} == {dirty, neighbor}

    def test_hal_id_listed_second_is_not_a_neighbor(self, sa_sync_conn):
        """La clé HAL d'une notice est le premier identifiant qu'elle liste : les suivants ne relient rien."""
        conn = sa_sync_conn
        dirty = insert_source_publication(
            conn,
            source="openalex",
            source_id="a",
            title="T",
            pub_year=2024,
            doc_type="article",
            external_ids={"hal_id": ["hal-2"]},
        )
        insert_source_publication(
            conn,
            source="openalex",
            source_id="b",
            title="T",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
            external_ids={"hal_id": ["hal-1", "hal-2"]},
        )
        assert {r.id for r in _Q.fetch_reconciliation_universe(conn)} == {dirty}

    def test_neighbor_by_metadata_block(self, sa_sync_conn):
        """Voisinage par token bloc métadonnée : deux SP de même doc_type + titre (long) + année, sans clé d'identifiant partagée (ici des thèses)."""
        conn = sa_sync_conn
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        dirty = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            title_normalized="ma these de doctorat au titre suffisamment long",
            pub_year=2024,
            doc_type="thesis",
        )
        neighbor = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            title_normalized="ma these de doctorat au titre suffisamment long",
            pub_year=2024,
            doc_type="thesis",
            keys_dirty=False,
        )
        assert {r.id for r in _Q.fetch_reconciliation_universe(conn)} == {dirty, neighbor}

    def test_dirty_orphan_included(self, sa_sync_conn):
        """Une SP orpheline dirty EST un seed : l'assignation est unifiée dans la réconciliation
        (elle se fait matcher / créer / skipper par le même primitif)."""
        conn = sa_sync_conn
        orphan = insert_source_publication(
            conn,
            source="openalex",
            source_id="orphan",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
        )
        assert _Q.fetch_dirty_source_publication_ids(conn) == [orphan]


class TestEndToEnd:
    def test_two_pubs_sharing_doi_merged(self, sa_sync_conn, monkeypatch):
        """Deux pubs dont les SP partagent un DOI → fusion. Les pubs n'ont pas (encore) le DOI en
        colonne (`UNIQUE(lower(doi))` interdit deux pubs au même DOI) : aucune ne le porte, donc
        l'ancre tombe sur le `min(source_publication_id)`."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        sp_a = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
        )
        sp_b = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
        )

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

    def test_sans_document_a_retraiter_le_journal_dit_rien_a_faire(
        self, sa_sync_conn, monkeypatch, caplog
    ):
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)

        with caplog.at_level(logging.INFO, logger=logger.name):
            run(
                conn,
                PgPublicationsReconciliationQueries(),
                logger,
                publication_repo=publication_repository(conn),
            )

        assert "Aucun document nouveau ou mis à jour" in caplog.text
        assert "Rien à faire" in caplog.text
        assert "Recalcul" not in caplog.text

    def test_le_journal_accorde_les_publications_resolues(self, sa_sync_conn, monkeypatch, caplog):
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub_a = _seed_pub(conn)
        pub_b = _seed_pub(conn)
        insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
        )
        insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
        )

        with caplog.at_level(logging.INFO, logger=logger.name):
            run(
                conn,
                PgPublicationsReconciliationQueries(),
                logger,
                publication_repo=publication_repository(conn),
            )

        assert "résolus en 1 publication (1 déjà existante, 0 nouvelle ; 1 doublon" in caplog.text

    def test_la_reconstruction_complete_s_annonce(self, sa_sync_conn, monkeypatch, caplog):
        """Sous `rebuild`, l'étape annonce une reconstruction complète."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        insert_source_publication(
            conn,
            _seed_pub(conn),
            source="openalex",
            source_id="a",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
        )

        with caplog.at_level(logging.INFO, logger=logger.name):
            run(
                conn,
                PgPublicationsReconciliationQueries(),
                logger,
                publication_repo=publication_repository(conn),
                rebuild=True,
            )

        assert "(reconstruction complète)" in caplog.text
        assert "nouveaux ou mis à jour" not in caplog.text

    def test_pub_with_two_dois_splits(self, sa_sync_conn, monkeypatch):
        """Une pub portant doi=X héberge une SP doi=Y (reliées par hal_id) → X garde la pub,
        Y part sur un nouveau pub."""
        conn = sa_sync_conn
        monkeypatch.setattr(conn, "commit", lambda: None)
        pub = _seed_pub(conn, doi="10.1/x")
        sp_x = insert_source_publication(
            conn,
            pub,
            source="openalex",
            source_id="x",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
            external_ids={"hal_id": ["h"]},
        )
        sp_y = insert_source_publication(
            conn,
            pub,
            source="openalex",
            source_id="y",
            title="T",
            doi="10.2/y",
            pub_year=2024,
            doc_type="article",
            external_ids={"hal_id": ["h"]},
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
        sp_a = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            title_normalized="ma these de doctorat au titre suffisamment long",
            pub_year=2024,
            doc_type="thesis",
        )
        sp_b = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            title_normalized="ma these de doctorat au titre suffisamment long",
            pub_year=2024,
            doc_type="thesis",
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
        sp_a = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            doi="10.1/x",
            pub_year=2024,
            doc_type="article",
            external_ids={"hal_id": ["hal-1"]},
        )
        sp_b = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            doi="10.2/y",
            pub_year=2024,
            doc_type="article",
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
        sp_a = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            title_normalized=self.LONG,
            pub_year=2024,
            doc_type="conference_paper",
        )
        sp_b = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            title_normalized=self.LONG,
            pub_year=2024,
            doc_type="conference_paper",
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
        sp_a = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            title_normalized="court titre",
            pub_year=2024,
            doc_type="conference_paper",
        )
        sp_b = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            title_normalized="court titre",
            pub_year=2024,
            doc_type="conference_paper",
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
        sp_a = insert_source_publication(
            conn,
            pub_a,
            source="openalex",
            source_id="a",
            title="T",
            title_normalized=self.LONG,
            pub_year=2024,
            doc_type="conference_paper",
        )
        sp_b = insert_source_publication(
            conn,
            pub_b,
            source="openalex",
            source_id="b",
            title="T",
            title_normalized=self.LONG,
            pub_year=2024,
            doc_type="book_chapter",
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
        a = insert_source_publication(
            conn,
            source="openalex",
            source_id="a",
            title="T",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
        )
        b = insert_source_publication(
            conn,
            source="openalex",
            source_id="b",
            title="T",
            pub_year=2024,
            doc_type="book_chapter",
            keys_dirty=False,
        )
        assert mark_keys_dirty(conn) >= 2
        assert _sp_state(conn, a)[1] is True
        assert _sp_state(conn, b)[1] is True

    def test_mark_where_targets_subset(self, sa_sync_conn):
        conn = sa_sync_conn
        art = insert_source_publication(
            conn,
            source="openalex",
            source_id="art",
            title="T",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
        )
        chap = insert_source_publication(
            conn,
            source="openalex",
            source_id="chap",
            title="T",
            pub_year=2024,
            doc_type="book_chapter",
            keys_dirty=False,
        )
        mark_keys_dirty(conn, "doc_type = 'book_chapter'")
        assert _sp_state(conn, chap)[1] is True
        assert _sp_state(conn, art)[1] is False

    def test_dry_run_counts_without_writing(self, sa_sync_conn):
        conn = sa_sync_conn
        sp = insert_source_publication(
            conn,
            source="openalex",
            source_id="d",
            title="T",
            pub_year=2024,
            doc_type="poster",
            keys_dirty=False,
        )
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
            insert_source_publication(
                conn,
                source="openalex",
                source_id="doi1",
                title="T",
                doi="10.1/x",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="doi2",
                title="T",
                doi="10.1/x",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="hal1",
                title="T",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
                external_ids={"hal_id": ["hal-00000001", "hal-00000002"]},
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="hal2",
                title="T",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
                external_ids={"hal_id": ["hal-00000002", "hal-00000003"]},
            ),
            # Préfixe de collection institutionnelle : le VO HALId doit l'accepter comme token
            # (sinon le SQL les rapproche mais le clustering Python non → divergence + non-fusion).
            # Le numéro fait 8 chiffres (docid CCSD), exigence du VO.
            insert_source_publication(
                conn,
                source="openalex",
                source_id="emse1",
                title="T",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
                external_ids={"hal_id": ["emse-04836977"]},
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="emse2",
                title="T",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
                external_ids={"hal_id": ["emse-04836977"]},
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="nnt1",
                title="T",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
                external_ids={"nnt": "2024UCA01"},
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="nnt2",
                title="T",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
                external_ids={"nnt": "2024UCA01"},
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="mb1",
                title="T",
                title_normalized=long_a,
                pub_year=2024,
                doc_type="conference_paper",
                keys_dirty=False,
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="mb2",
                title="T",
                title_normalized=long_a,
                pub_year=2024,
                doc_type="conference_paper",
                keys_dirty=False,
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="mbo",
                title="T",
                title_normalized=long_b,
                pub_year=2024,
                doc_type="conference_paper",
                keys_dirty=False,
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="s1",
                title="T",
                title_normalized=len30,
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="s2",
                title="T",
                title_normalized=len30,
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
            ),
            insert_source_publication(
                conn,
                source="openalex",
                source_id="lone",
                title="T",
                title_normalized="zz",
                pub_year=2024,
                doc_type="article",
                keys_dirty=False,
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
            sql_neighbors = {r.id for r in _Q.fetch_reconciliation_universe(conn)} & seeded - {i}
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
        sp1 = insert_source_publication(
            conn,
            source="openalex",
            source_id="t1",
            title="T",
            title_normalized="t",
            doi="10.70675/abc",
            pub_year=2024,
            doc_type="article",
        )
        sp2 = insert_source_publication(
            conn,
            source="openalex",
            source_id="t2",
            title="T",
            doi="10.70675/abc",
            pub_year=2024,
            doc_type="article",
        )
        # in_perimeter → sans le correctif, ce groupe d'orphelins serait une CRÉATION et
        # planterait sur publications_doi_lower_key ; avec, il s'ancre sur la pub existante.
        conn.execute(
            text(
                "INSERT INTO source_authorships"
                " (source, source_publication_id, in_perimeter, identity_id, raw_author_name) "
                "VALUES ('openalex', :sp, true, :iid, 'X')"
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


def _distinct_dois(conn, pub_id) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT DISTINCT doi FROM source_publications "
                "WHERE publication_id = :id AND doi IS NOT NULL"
            ),
            {"id": pub_id},
        ).scalars()
    )


class TestDeletePublicationsWithoutSources:
    def test_only_publications_without_source_are_deleted(self, sa_sync_conn):
        conn = sa_sync_conn
        vide = _seed_pub(conn)
        garnie = _seed_pub(conn, doi="10.1/garnie")
        insert_source_publication(
            conn,
            garnie,
            source="openalex",
            source_id="garnie",
            title="T",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
        )

        assert _Q.delete_publications_without_sources(conn) == 1
        assert not _pub_exists(conn, vide)
        assert _pub_exists(conn, garnie)


class TestStaleMembership:
    """Régression : une source_publication rattachée par une clé de confirmation qui disparaît
    ensuite doit être détachée, pas laissée sur une publication que plus rien ne lui associe.

    Cas typique : une préversion arXiv rejoint la publication tant que l'enregistrement OpenAlex
    porte le DOI de la préversion, puis la source bascule sur le DOI de la version publiée. Le
    voisinage 1-hop se calcule sur les clés d'après : la préversion n'y figure dans aucun bras, et
    seule la propagation de `keys_dirty` aux source_publications co-rattachées la ramène dans la
    passe. Sans elle, la publication porte deux DOI distincts.
    """

    PREPRINT_DOI = "10.48550/arxiv.2409.20505"
    PUBLISHED_DOI = "10.1016/j.tcs.2026.116186"

    def _seed_drifted_pair(self, conn) -> tuple[int, int, int]:
        """Une publication au DOI de préversion, ses deux SP, et plus aucune clé partagée entre
        elles : DOI distincts, aucun identifiant commun, titres absents (pas de token bloc)."""
        pub = _seed_pub(conn, doi=self.PREPRINT_DOI)
        preprint = insert_source_publication(
            conn,
            pub,
            source="openalex",
            source_id="preprint",
            title="T",
            doi=self.PREPRINT_DOI,
            pub_year=2024,
            doc_type="preprint",
            keys_dirty=False,
        )
        published = insert_source_publication(
            conn,
            pub,
            source="openalex",
            source_id="published",
            title="T",
            doi=self.PUBLISHED_DOI,
            pub_year=2024,
            doc_type="article",
        )
        return pub, preprint, published

    def test_siblings_of_a_dirty_source_publication_are_marked(self, sa_sync_conn):
        """La propagation marque les co-rattachées, et elles seules : ni les SP d'une autre
        publication, ni les orphelines."""
        conn = sa_sync_conn
        _, preprint, _ = self._seed_drifted_pair(conn)
        other = insert_source_publication(
            conn,
            _seed_pub(conn),
            source="openalex",
            source_id="other",
            title="T",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
        )
        orphan = insert_source_publication(
            conn,
            source="openalex",
            source_id="orphan",
            title="T",
            pub_year=2024,
            doc_type="article",
            keys_dirty=False,
        )

        assert _Q.mark_publication_siblings_dirty(conn) == 1
        assert _sp_state(conn, preprint)[1] is True
        assert _sp_state(conn, other)[1] is False
        assert _sp_state(conn, orphan)[1] is False

    def test_source_publication_without_shared_key_is_split_off(self, sa_sync_conn):
        conn = sa_sync_conn
        pub, preprint, published = self._seed_drifted_pair(conn)

        reconcile(conn, _Q, publication_repo=publication_repository(conn))

        preprint_pub, preprint_dirty = _sp_state(conn, preprint)
        published_pub, published_dirty = _sp_state(conn, published)
        assert preprint_pub != published_pub
        # Ancre = porteur du DOI : la publication reste à la préversion, dont elle porte le DOI.
        assert preprint_pub == pub
        assert (preprint_dirty, published_dirty) == (False, False)
        assert _distinct_dois(conn, preprint_pub) == {self.PREPRINT_DOI}
        assert _distinct_dois(conn, published_pub) == {self.PUBLISHED_DOI}


class TestFirstHalIdKey:
    """Une notice qui liste deux dépôts HAL rejoint la publication du premier, et laisse les deux dépôts distincts."""

    def test_bridge_notice_joins_first_listed_deposit_only(self, sa_sync_conn):
        conn = sa_sync_conn
        pub = _seed_pub(conn)
        first = insert_source_publication(
            conn,
            pub,
            source="openalex",
            source_id="hal-01234567",
            title="T",
            pub_year=2024,
            doc_type="conference_paper",
            external_ids={"hal_id": ["hal-01234567"]},
        )
        second = insert_source_publication(
            conn,
            pub,
            source="openalex",
            source_id="hal-07654321",
            title="T",
            pub_year=2024,
            doc_type="book_chapter",
            external_ids={"hal_id": ["hal-07654321"]},
        )
        bridge = insert_source_publication(
            conn,
            pub,
            source="openalex",
            source_id="W1",
            title="T",
            pub_year=2024,
            doc_type="article",
            external_ids={"hal_id": ["hal-01234567", "hal-07654321"]},
        )

        reconcile(conn, _Q, publication_repo=publication_repository(conn))

        assert _sp_state(conn, bridge)[0] == _sp_state(conn, first)[0]
        assert _sp_state(conn, second)[0] != _sp_state(conn, first)[0]
