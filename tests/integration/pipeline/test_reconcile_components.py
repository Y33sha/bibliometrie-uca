"""Intégration : passe de réconciliation des composantes (merge-only).

Valide le SQL (voisinage 1-hop, relevé de la file, suppression des marquages) sur vraie base, et le bout-en-bout `reconcile()` (fusion + suppression des marquages traités), dans la transaction rollbackée.
"""

import logging
from functools import partial

from sqlalchemy import bindparam, text

from domain.merge import MergedEntity
from domain.publications.reconciliation import manual_merge_tokens
from domain.source_records.keys import project_confirmation_keys
from infrastructure.db.queues import Queue
from pipeline.transformation.publications.reconciliation import (
    fetch_reconciliation_universe,
    mark_for_reconciliation,
    mark_publication_siblings,
    reconcile,
    reconcile_source_records,
    snapshot_queued_source_records,
)
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.queues import clear, mark, queued
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

# Enregistrement source OpenAlex de 2024, de titre « T », article par défaut.
_source_record = partial(
    insert_source_record, source="openalex", title="T", publication_year=2024, doc_type="article"
)

logger = logging.getLogger("test_reconcile_components")


def _seed_publication(conn, doi=None) -> int:
    return PublicationStore(conn).create(
        title="T",
        title_normalized="t",
        doc_type="article",
        publication_year=2024,
        doi=doi,
        oa_status="unknown",
    )


def _publication_exists(conn, publication_id) -> bool:
    return (
        conn.execute(
            text("SELECT 1 FROM publications WHERE id = :id"), {"id": publication_id}
        ).first()
        is not None
    )


def _source_record_state(conn, source_record_id) -> tuple:
    """`publication_id` de l'enregistrement source, et sa présence dans la file de la réconciliation."""
    publication_id = conn.execute(
        text("SELECT publication_id FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()
    return publication_id, source_record_id in queued(conn, Queue.SOURCE_RECORD_KEYS)


def _manual_merge(conn, source_record_ids) -> int:
    """Enregistre une fusion manuelle des enregistrements sources `source_record_ids`, par leur clé naturelle. Rend son identifiant."""
    manual_merge_id = conn.execute(
        text("INSERT INTO manual_merges DEFAULT VALUES RETURNING id")
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO manual_merge_source_records (manual_merge_id, source, source_id) "
            "SELECT :merge, source, source_id FROM source_records WHERE id = ANY(:ids)"
        ).bindparams(bindparam("ids")),
        {"merge": manual_merge_id, "ids": list(source_record_ids)},
    )
    return manual_merge_id


def _universe(conn) -> set[int]:
    """Relève la file, puis rend les identifiants du voisinage 1-hop."""
    snapshot_queued_source_records(conn)
    return {r.id for r in fetch_reconciliation_universe(conn)}


class TestUniverse:
    def test_fetches_dirty_and_one_hop_neighbor(self, sa_sync_conn):
        """Le voisinage = enregistrement source dirty + enregistrement source non-dirty partageant une clé ; ignore les non-liées.

        DOI présent sur les enregistrements sources, pas sur les publications (`UNIQUE(lower(doi))` interdit deux publications
        au même DOI) ; le voisinage par DOI joint sur `source_records.doi`."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        unrelated_publication = _seed_publication(conn)
        dirty = _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        neighbor = _source_record(conn, publication_b, source_id="b", doi="10.1/x", marked=False)
        _source_record(conn, unrelated_publication, source_id="c", doi="10.9/z", marked=False)

        assert _universe(conn) == {dirty, neighbor}

    def test_neighbor_by_hal_id(self, sa_sync_conn):
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        dirty = _source_record(
            conn, publication_a, source_id="a", external_ids={"hal_id": ["hal-01000001"]}
        )
        neighbor = _source_record(
            conn,
            publication_b,
            source_id="b",
            marked=False,
            external_ids={"hal_id": ["hal-01000001", "hal-01000002"]},
        )
        assert _universe(conn) == {dirty, neighbor}

    def test_hal_id_listed_second_is_not_a_neighbor(self, sa_sync_conn):
        """La clé HAL d'un enregistrement source est le premier identifiant qu'il liste : les suivants ne relient rien."""
        conn = sa_sync_conn
        dirty = _source_record(conn, source_id="a", external_ids={"hal_id": ["hal-01000002"]})
        _source_record(
            conn,
            source_id="b",
            marked=False,
            external_ids={"hal_id": ["hal-01000001", "hal-01000002"]},
        )
        assert _universe(conn) == {dirty}

    def test_neighbor_by_metadata_block(self, sa_sync_conn):
        """Voisinage par token bloc métadonnée : deux enregistrements sources de même doc_type + titre (long) + année, sans clé d'identifiant partagée (ici des thèses)."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        dirty = _source_record(
            conn,
            publication_a,
            source_id="a",
            title_normalized="ma these de doctorat au titre suffisamment long",
            doc_type="thesis",
        )
        neighbor = _source_record(
            conn,
            publication_b,
            source_id="b",
            title_normalized="ma these de doctorat au titre suffisamment long",
            doc_type="thesis",
            marked=False,
        )
        assert _universe(conn) == {dirty, neighbor}

    def test_neighbor_by_manual_merge(self, sa_sync_conn_owner):
        """Deux enregistrements sources sans clé de confirmation commune, désignés par une même fusion manuelle."""
        conn = sa_sync_conn_owner
        dirty = _source_record(conn, _seed_publication(conn), source_id="a", doi="10.1/x")
        neighbor = _source_record(
            conn,
            _seed_publication(conn),
            source_id="b",
            source="hal",
            external_ids={"hal_id": ["hal-04263452"]},
            marked=False,
        )
        _source_record(conn, _seed_publication(conn), source_id="c", marked=False)
        _manual_merge(conn, [dirty, neighbor])

        assert _universe(conn) == {dirty, neighbor}

    def test_dirty_orphan_included(self, sa_sync_conn):
        """Un enregistrement source orpheline dirty EST un seed : l'assignation est unifiée dans la réconciliation
        (elle se fait matcher / créer / skipper par le même primitif)."""
        conn = sa_sync_conn
        orphan = _source_record(conn, source_id="orphan", doi="10.1/x")
        assert snapshot_queued_source_records(conn) == [orphan]


class TestEndToEnd:
    def test_two_publications_sharing_doi_merged(self, sa_sync_conn):
        """Deux publications dont les enregistrements sources partagent un DOI → fusion. Les publications n'ont pas (encore) le DOI en
        colonne (`UNIQUE(lower(doi))` interdit deux publications au même DOI) : aucune ne l'a, donc
        l'ancre tombe sur le `min(source_record_id)`."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        source_record_a = _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        source_record_b = _source_record(conn, publication_b, source_id="b", doi="10.1/x")

        reconcile(conn, logger)

        # Aucune publication n'a le DOI en colonne → ancre = publication du plus petit source_record_id.
        anchor, absorbed = (
            (publication_a, publication_b)
            if source_record_a < source_record_b
            else (publication_b, publication_a)
        )
        assert _publication_exists(conn, anchor)
        assert not _publication_exists(conn, absorbed)
        assert redirect_of(conn, MergedEntity.PUBLICATION, absorbed) == anchor
        assert _source_record_state(conn, source_record_a) == (anchor, False)
        assert _source_record_state(conn, source_record_b) == (anchor, False)

    def test_publication_keeping_sources_outside_neighborhood_survives_without_redirect(
        self, sa_sync_conn
    ):
        """L'enregistrement source voisin rejoint l'ancre ; sa publication garde un autre enregistrement source, hors du voisinage. Elle survit, sans redirection."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        source_record_a = _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        source_record_b = _source_record(
            conn, publication_b, source_id="b", doi="10.1/x", marked=False
        )
        source_record_other = _source_record(
            conn, publication_b, source_id="c", doi="10.1/y", marked=False
        )

        reconcile(conn, logger)

        assert _source_record_state(conn, source_record_a)[0] == publication_a
        assert _source_record_state(conn, source_record_b)[0] == publication_a
        assert _source_record_state(conn, source_record_other)[0] == publication_b
        assert _publication_exists(conn, publication_b)
        assert redirect_of(conn, MergedEntity.PUBLICATION, publication_b) is None

    def test_les_publications_touchees_regroupent_leurs_contributions_sources(self, sa_sync_conn):
        """La publication qui reçoit un enregistrement source et celle qui en perd un sont à regrouper. Une publication dont l'enregistrement source réexaminé reste en place ne l'est pas."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        untouched = _seed_publication(conn)
        _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        _source_record(conn, publication_b, source_id="b", doi="10.1/x", marked=False)
        _source_record(conn, publication_b, source_id="c", doi="10.1/y", marked=False)
        _source_record(conn, untouched, source_id="d", doi="10.9/z")
        clear(conn, Queue.PUBLICATION_CONTRIBUTIONS)

        reconcile(conn, logger)

        marked = queued(conn, Queue.PUBLICATION_CONTRIBUTIONS)
        assert {publication_a, publication_b} <= marked
        assert untouched not in marked

    def test_sans_document_a_retraiter_le_journal_dit_rien_a_faire(self, sa_sync_conn, caplog):
        conn = sa_sync_conn

        with caplog.at_level(logging.INFO, logger=logger.name):
            reconcile(conn, logger)

        assert "Aucun document nouveau ou mis à jour" in caplog.text
        assert "Rien à faire" in caplog.text
        assert "Recalcul" not in caplog.text

    def test_le_journal_accorde_les_publications_resolues(self, sa_sync_conn, caplog):
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        _source_record(conn, publication_b, source_id="b", doi="10.1/x")

        with caplog.at_level(logging.INFO, logger=logger.name):
            reconcile(conn, logger)

        assert "résolus en 1 publication (1 déjà existante, 0 nouvelle ; 1 doublon" in caplog.text

    def test_la_reconstruction_complete_s_annonce(self, sa_sync_conn, caplog):
        """Sous `rebuild`, l'étape annonce une reconstruction complète."""
        conn = sa_sync_conn
        _source_record(conn, _seed_publication(conn), source_id="a", doi="10.1/x")

        with caplog.at_level(logging.INFO, logger=logger.name):
            reconcile(
                conn,
                logger,
                rebuild=True,
            )

        assert "(reconstruction complète)" in caplog.text
        assert "nouveaux ou mis à jour" not in caplog.text

    def test_publication_with_two_dois_splits(self, sa_sync_conn):
        """Une publication qui a doi=X héberge un enregistrement source doi=Y (reliées par hal_id) → X garde la publication,
        Y part sur une nouvelle publication."""
        conn = sa_sync_conn
        publication = _seed_publication(conn, doi="10.1/x")
        source_record_x = _source_record(
            conn, publication, source_id="x", doi="10.1/x", external_ids={"hal_id": ["h"]}
        )
        source_record_y = _source_record(
            conn, publication, source_id="y", doi="10.2/y", external_ids={"hal_id": ["h"]}
        )

        reconcile(conn, logger)

        # X garde la publication d'origine ; Y est parti sur un autre publication (créé).
        assert _source_record_state(conn, source_record_x) == (publication, False)
        y_publication, y_dirty = _source_record_state(conn, source_record_y)
        assert y_publication != publication
        assert y_dirty is False
        assert _publication_exists(conn, publication)
        assert _publication_exists(conn, y_publication)

    def test_two_theses_sharing_title_year_merged(self, sa_sync_conn):
        """Deux thèses cross-source, même titre (long) + année, sans DOI/NNT/hal partagé → fusion par token bloc métadonnée."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        source_record_a = _source_record(
            conn,
            publication_a,
            source_id="a",
            title_normalized="ma these de doctorat au titre suffisamment long",
            doc_type="thesis",
        )
        source_record_b = _source_record(
            conn,
            publication_b,
            source_id="b",
            title_normalized="ma these de doctorat au titre suffisamment long",
            doc_type="thesis",
        )

        reconcile(conn, logger)

        anchor, absorbed = (
            (publication_a, publication_b)
            if source_record_a < source_record_b
            else (publication_b, publication_a)
        )
        assert _publication_exists(conn, anchor)
        assert not _publication_exists(conn, absorbed)
        assert _source_record_state(conn, source_record_a) == (anchor, False)
        assert _source_record_state(conn, source_record_b) == (anchor, False)

    def test_distinct_dois_not_merged(self, sa_sync_conn):
        """Deux publications à DOI distincts partageant un hal_id : pas de fusion (cannot-link DOI)."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn, doi="10.1/x")
        publication_b = _seed_publication(conn, doi="10.2/y")
        hal_id = {"hal_id": ["hal-01000001"]}
        source_record_a = _source_record(
            conn, publication_a, source_id="a", doi="10.1/x", external_ids=hal_id
        )
        source_record_b = _source_record(
            conn, publication_b, source_id="b", doi="10.2/y", external_ids=hal_id
        )

        reconcile(conn, logger)

        assert _publication_exists(conn, publication_a)
        assert _publication_exists(conn, publication_b)
        # Drapeaux nettoyés malgré l'absence de fusion (les enregistrements sources ont été réconciliées).
        assert _source_record_state(conn, source_record_a)[1] is False
        assert _source_record_state(conn, source_record_b)[1] is False

    def test_publication_of_a_residual_source_record_is_refreshed(self, sa_sync_conn):
        """Régression : l'enregistrement source sans DOI d'une composante à deux DOI reste sur sa publication, qui gardait le DOI qu'il avait perdu."""
        conn = sa_sync_conn
        hal_id = {"hal_id": ["hal-01234567"]}
        stale = _seed_publication(conn, doi="10.9/retire")
        residual = _source_record(conn, stale, source_id="a", external_ids=hal_id)
        for source_id, doi in (("b", "10.1/x"), ("c", "10.2/y")):
            _source_record(
                conn,
                _seed_publication(conn, doi=doi),
                source_id=source_id,
                doi=doi,
                marked=False,
                external_ids=hal_id,
            )
        assert (
            conn.execute(
                text("SELECT doi FROM publications WHERE id = :id"), {"id": stale}
            ).scalar()
            == "10.9/retire"
        )

        reconcile(conn, logger)

        assert _source_record_state(conn, residual) == (stale, False)
        assert (
            conn.execute(
                text("SELECT doi FROM publications WHERE id = :id"), {"id": stale}
            ).scalar()
            is None
        )


class TestManualMerge:
    def test_publications_without_shared_key_merged_into_doi_carrier(self, sa_sync_conn_owner):
        """Un article à DOI et le dépôt HAL sans DOI de cet article, au titre différent : la fusion manuelle les réunit dans la publication qui a le DOI."""
        conn = sa_sync_conn_owner
        with_doi = _seed_publication(conn, doi="10.64628/aak.7y96696up")
        without_doi = _seed_publication(conn)
        crossref = _source_record(
            conn, with_doi, source="crossref", source_id="crossref", doi="10.64628/aak.7y96696up"
        )
        hal = _source_record(
            conn,
            without_doi,
            source="hal",
            source_id="hal-04263452",
            external_ids={"hal_id": ["hal-04263452"]},
        )
        _manual_merge(conn, [crossref, hal])

        reconcile(conn, logger)

        assert _source_record_state(conn, crossref) == (with_doi, False)
        assert _source_record_state(conn, hal) == (with_doi, False)
        assert not _publication_exists(conn, without_doi)
        assert redirect_of(conn, MergedEntity.PUBLICATION, without_doi) == with_doi

    def test_publications_with_distinct_dois_kept_apart(self, sa_sync_conn_owner):
        """La fusion manuelle respecte la règle « un DOI, une œuvre »."""
        conn = sa_sync_conn_owner
        publication_a = _seed_publication(conn, doi="10.1/x")
        publication_b = _seed_publication(conn, doi="10.2/y")
        source_record_a = _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        source_record_b = _source_record(conn, publication_b, source_id="b", doi="10.2/y")
        _manual_merge(conn, [source_record_a, source_record_b])

        reconcile(conn, logger)

        assert _source_record_state(conn, source_record_a)[0] == publication_a
        assert _source_record_state(conn, source_record_b)[0] == publication_b


class TestReconcileSourceRecords:
    def test_merges_the_neighborhood_of_the_listed_source_records(self, sa_sync_conn_owner):
        """La liste suffit : les enregistrements sources rattachés aux mêmes publications et leurs voisins entrent dans la passe."""
        conn = sa_sync_conn_owner
        with_doi = _seed_publication(conn, doi="10.1/x")
        without_doi = _seed_publication(conn)
        crossref = _source_record(
            conn, with_doi, source="crossref", source_id="c", doi="10.1/x", marked=False
        )
        hal = _source_record(
            conn,
            without_doi,
            source="hal",
            source_id="hal-04263452",
            external_ids={"hal_id": ["hal-04263452"]},
            marked=False,
        )
        sibling = _source_record(
            conn,
            without_doi,
            source_id="W1",
            external_ids={"hal_id": ["hal-04263452"]},
            marked=False,
        )
        _manual_merge(conn, [crossref, hal])

        applied = reconcile_source_records(conn, [hal])

        assert {_source_record_state(conn, i)[0] for i in (crossref, hal, sibling)} == {with_doi}
        assert not _publication_exists(conn, without_doi)
        assert applied.survivors == {with_doi}
        assert applied.changed == {with_doi}
        assert with_doi in queued(conn, Queue.PUBLICATION_CONTRIBUTIONS)

    def test_leaves_the_queue_untouched(self, sa_sync_conn):
        """Les marquages de la file restent en place, pour le prochain passage du pipeline."""
        conn = sa_sync_conn
        listed = _source_record(conn, _seed_publication(conn), source_id="a", marked=False)
        queued_elsewhere = _source_record(conn, _seed_publication(conn), source_id="b")

        reconcile_source_records(conn, [listed])

        assert queued(conn, Queue.SOURCE_RECORD_KEYS) & {listed, queued_elsewhere} == {
            queued_elsewhere
        }

    def test_refreshes_the_consolidated_metadata(self, sa_sync_conn):
        """La publication conservée reprend ses métadonnées de ses sources."""
        conn = sa_sync_conn
        publication = _seed_publication(conn)
        source_record = _source_record(
            conn, publication, source_id="a", title="Titre de la source", marked=False
        )

        reconcile_source_records(conn, [source_record])

        title = conn.execute(
            text("SELECT title FROM publications WHERE id = :id"), {"id": publication}
        ).scalar_one()
        assert title == "Titre de la source"


class TestMetadataBlock:
    LONG = "une communication scientifique au titre assez long"

    def test_two_conference_papers_merged(self, sa_sync_conn):
        """Deux conference_paper cross-source, même titre (long) + année, sans DOI → fusion par token bloc."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        source_record_a = _source_record(
            conn,
            publication_a,
            source_id="a",
            title_normalized=self.LONG,
            doc_type="conference_paper",
        )
        source_record_b = _source_record(
            conn,
            publication_b,
            source_id="b",
            title_normalized=self.LONG,
            doc_type="conference_paper",
        )

        reconcile(conn, logger)

        anchor, absorbed = (
            (publication_a, publication_b)
            if source_record_a < source_record_b
            else (publication_b, publication_a)
        )
        assert _publication_exists(conn, anchor)
        assert not _publication_exists(conn, absorbed)
        assert _source_record_state(conn, source_record_a) == (anchor, False)
        assert _source_record_state(conn, source_record_b) == (anchor, False)

    def test_short_title_not_merged(self, sa_sync_conn):
        """Titre court (≤ seuil) → pas de token bloc, pas de fusion (garde de longueur)."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        source_record_a = _source_record(
            conn,
            publication_a,
            source_id="a",
            title_normalized="court titre",
            doc_type="conference_paper",
        )
        source_record_b = _source_record(
            conn,
            publication_b,
            source_id="b",
            title_normalized="court titre",
            doc_type="conference_paper",
        )

        reconcile(conn, logger)

        assert _publication_exists(conn, publication_a)
        assert _publication_exists(conn, publication_b)
        assert _source_record_state(conn, source_record_a)[1] is False
        assert _source_record_state(conn, source_record_b)[1] is False

    def test_different_doc_type_not_merged(self, sa_sync_conn):
        """Même titre long + année mais doc_type différents → pas de fusion (doc_type dans la clé)."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        source_record_a = _source_record(
            conn,
            publication_a,
            source_id="a",
            title_normalized=self.LONG,
            doc_type="conference_paper",
        )
        source_record_b = _source_record(
            conn, publication_b, source_id="b", title_normalized=self.LONG, doc_type="book_chapter"
        )

        reconcile(conn, logger)

        assert _publication_exists(conn, publication_a)
        assert _publication_exists(conn, publication_b)
        assert _source_record_state(conn, source_record_a)[1] is False
        assert _source_record_state(conn, source_record_b)[1] is False


class TestMarkForReconciliation:
    """Primitive de re-matérialisation : marquage total ou ciblé (CLI maintenance + flag rebuild)."""

    def test_mark_all(self, sa_sync_conn):
        conn = sa_sync_conn
        a = _source_record(conn, source_id="a", marked=False)
        b = _source_record(conn, source_id="b", doc_type="book_chapter", marked=False)
        assert mark_for_reconciliation(conn) >= 2
        assert _source_record_state(conn, a)[1] is True
        assert _source_record_state(conn, b)[1] is True

    def test_mark_where_targets_subset(self, sa_sync_conn):
        conn = sa_sync_conn
        art = _source_record(conn, source_id="art", marked=False)
        chap = _source_record(conn, source_id="chap", doc_type="book_chapter", marked=False)
        mark_for_reconciliation(conn, "doc_type = 'book_chapter'")
        assert _source_record_state(conn, chap)[1] is True
        assert _source_record_state(conn, art)[1] is False

    def test_dry_run_counts_without_writing(self, sa_sync_conn):
        conn = sa_sync_conn
        source_record = _source_record(conn, source_id="d", doc_type="poster", marked=False)
        assert mark_for_reconciliation(conn, "doc_type = 'poster'", dry_run=True) >= 1
        assert _source_record_state(conn, source_record)[1] is False  # dry-run n'écrit pas


class TestUniverseMatchesPythonTokens:
    """Différentiel anti-divergence : le voisinage SQL (branches d'univers) relie exactement les
    enregistrement source que les tokens Python (`project_confirmation_keys`) relient. Les deux encodages du même
    critère d'égalité doivent s'accorder — surtout la garde de longueur `metadata_block`.

    Pour chaque enregistrement source, on le marque seul dirty et on compare son voisinage 1-hop SQL à l'ensemble
    des enregistrements sources dont les tokens Python intersectent les siens.
    """

    def test_sql_universe_matches_python_token_linkage(self, sa_sync_conn_owner):
        conn = sa_sync_conn_owner
        long_a, long_b = "a" * 40, "b" * 40
        len30 = "c" * 30  # juste SOUS le seuil strict > 30 → pas de token metadata_block
        ids = [
            _source_record(conn, source_id="doi1", doi="10.1/x", marked=False),
            _source_record(conn, source_id="doi2", doi="10.1/x", marked=False),
            _source_record(
                conn,
                source_id="hal1",
                marked=False,
                external_ids={"hal_id": ["hal-00000001", "hal-00000002"]},
            ),
            _source_record(
                conn,
                source_id="hal2",
                marked=False,
                external_ids={"hal_id": ["hal-00000002", "hal-00000003"]},
            ),
            # Préfixe de collection institutionnelle : le VO HALId doit l'accepter comme token
            # (sinon le SQL les rapproche mais le clustering Python non → divergence + non-fusion).
            # Le numéro fait 8 chiffres (docid CCSD), exigence du VO.
            _source_record(
                conn,
                source_id="emse1",
                marked=False,
                external_ids={"hal_id": ["emse-04836977"]},
            ),
            _source_record(
                conn,
                source_id="emse2",
                marked=False,
                external_ids={"hal_id": ["emse-04836977"]},
            ),
            _source_record(conn, source_id="nnt1", marked=False, external_ids={"nnt": "2024UCA01"}),
            _source_record(conn, source_id="nnt2", marked=False, external_ids={"nnt": "2024UCA01"}),
            _source_record(
                conn,
                source_id="mb1",
                title_normalized=long_a,
                doc_type="conference_paper",
                marked=False,
            ),
            _source_record(
                conn,
                source_id="mb2",
                title_normalized=long_a,
                doc_type="conference_paper",
                marked=False,
            ),
            _source_record(
                conn,
                source_id="mbo",
                title_normalized=long_b,
                doc_type="conference_paper",
                marked=False,
            ),
            _source_record(conn, source_id="s1", title_normalized=len30, marked=False),
            _source_record(conn, source_id="s2", title_normalized=len30, marked=False),
            _source_record(conn, source_id="lone", title_normalized="zz", marked=False),
            _source_record(conn, source_id="mm1", title_normalized="yy", marked=False),
            _source_record(conn, source_id="mm2", title_normalized="xx", marked=False),
        ]
        manual_merge = _manual_merge(conn, ids[-2:])
        rows = {
            r.id: r
            for r in conn.execute(
                text(
                    "SELECT id, doi, external_ids, doc_type, title_normalized, publication_year "
                    "FROM source_records WHERE id = ANY(:ids)"
                ).bindparams(bindparam("ids")),
                {"ids": ids},
            )
        }
        toks = {
            i: project_confirmation_keys(
                r.doi, r.external_ids, r.doc_type, r.title_normalized, r.publication_year
            ).tokens()
            for i, r in rows.items()
        }
        for i in ids[-2:]:
            toks[i] |= manual_merge_tokens([manual_merge])
        seeded = set(ids)
        for i in ids:
            clear(conn, Queue.SOURCE_RECORD_KEYS)
            mark(conn, Queue.SOURCE_RECORD_KEYS, [i])
            sql_neighbors = _universe(conn) & seeded - {i}
            py_neighbors = {j for j in ids if j != i and toks[i] & toks[j]}
            assert sql_neighbors == py_neighbors, (
                f"divergence enregistrement source {i} : SQL={sql_neighbors} Python={py_neighbors}"
            )


class TestExternalDoiCarrier:
    """Régression : une publication orpheline (sans enregistrement source) qui a un DOI — état typique après un
    TRUNCATE + réimport des sources — ne doit pas faire planter la réconciliation. Les enregistrements sources fraîches
    qui ont ce DOI s'y rattachent au lieu de créer une publication neuve (qui violerait l'unicité du DOI)."""

    def test_orphan_publication_with_doi_is_reused_not_duplicated(self, sa_sync_conn):
        conn = sa_sync_conn
        orphan_publication = _seed_publication(
            conn, doi="10.70675/abc"
        )  # a le DOI, aucun enregistrement source
        sp1 = _source_record(conn, source_id="t1", title_normalized="t", doi="10.70675/abc")
        sp2 = _source_record(conn, source_id="t2", doi="10.70675/abc")
        # in_perimeter → sans le correctif, ce groupe d'orphelins serait une CRÉATION et
        # planterait sur publications_doi_lower_key ; avec, il s'ancre sur la publication existante.
        insert_source_contribution(
            conn, sp1, source="openalex", author_position=None, in_perimeter=True
        )

        reconcile(conn, logger)

        assert _publication_exists(conn, orphan_publication)
        assert _source_record_state(conn, sp1)[0] == orphan_publication
        assert _source_record_state(conn, sp2)[0] == orphan_publication
        n = conn.execute(
            text("SELECT count(*) FROM publications WHERE lower(doi) = '10.70675/abc'")
        ).scalar_one()
        assert n == 1


def _distinct_dois(conn, publication_id) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT DISTINCT doi FROM source_records "
                "WHERE publication_id = :id AND doi IS NOT NULL"
            ),
            {"id": publication_id},
        ).scalars()
    )


class TestStaleMembership:
    """Régression : une source_record rattachée par une clé de confirmation qui disparaît
    ensuite doit être détachée, pas laissée sur une publication que plus rien ne lui associe.

    Cas typique : une préversion arXiv rejoint la publication tant que l'enregistrement OpenAlex
    porte le DOI de la préversion, puis la source bascule sur le DOI de la version publiée. Le
    voisinage 1-hop se calcule sur les clés d'après : la préversion n'y figure dans aucun bras, et
    seul le marquage des source_records co-rattachées la ramène dans la
    passe. Sans elle, la publication porte deux DOI distincts.
    """

    PREPRINT_DOI = "10.48550/arxiv.2409.20505"
    PUBLISHED_DOI = "10.1016/j.tcs.2026.116186"

    def _seed_drifted_pair(self, conn) -> tuple[int, int, int]:
        """Une publication au DOI de préversion, ses deux enregistrements sources, et plus aucune clé partagée entre
        elles : DOI distincts, aucun identifiant commun, titres absents (pas de token bloc)."""
        publication = _seed_publication(conn, doi=self.PREPRINT_DOI)
        preprint = _source_record(
            conn,
            publication,
            source_id="preprint",
            doi=self.PREPRINT_DOI,
            doc_type="preprint",
            marked=False,
        )
        published = _source_record(conn, publication, source_id="published", doi=self.PUBLISHED_DOI)
        return publication, preprint, published

    def test_siblings_of_a_dirty_source_record_are_marked(self, sa_sync_conn):
        """La propagation marque les co-rattachées, et elles seules : ni les enregistrements sources d'une autre
        publication, ni les orphelines."""
        conn = sa_sync_conn
        _, preprint, _ = self._seed_drifted_pair(conn)
        other = _source_record(conn, _seed_publication(conn), source_id="other", marked=False)
        orphan = _source_record(conn, source_id="orphan", marked=False)

        assert mark_publication_siblings(conn) == 1
        assert _source_record_state(conn, preprint)[1] is True
        assert _source_record_state(conn, other)[1] is False
        assert _source_record_state(conn, orphan)[1] is False

    def test_source_record_without_shared_key_is_split_off(self, sa_sync_conn):
        conn = sa_sync_conn
        publication, preprint, published = self._seed_drifted_pair(conn)

        reconcile(conn, logger)

        preprint_publication, preprint_dirty = _source_record_state(conn, preprint)
        published_publication, published_dirty = _source_record_state(conn, published)
        assert preprint_publication != published_publication
        # Ancre = porteur du DOI : la publication reste à la préversion, dont elle porte le DOI.
        assert preprint_publication == publication
        assert (preprint_dirty, published_dirty) == (False, False)
        assert _distinct_dois(conn, preprint_publication) == {self.PREPRINT_DOI}
        assert _distinct_dois(conn, published_publication) == {self.PUBLISHED_DOI}


class TestFirstHalIdKey:
    """Un enregistrement source qui liste deux dépôts HAL rejoint la publication du premier, et laisse les deux dépôts distincts."""

    def test_bridge_source_record_joins_first_listed_deposit_only(self, sa_sync_conn):
        conn = sa_sync_conn
        publication = _seed_publication(conn)
        first = _source_record(
            conn,
            publication,
            source_id="hal-01234567",
            doc_type="conference_paper",
            external_ids={"hal_id": ["hal-01234567"]},
        )
        second = _source_record(
            conn,
            publication,
            source_id="hal-07654321",
            doc_type="book_chapter",
            external_ids={"hal_id": ["hal-07654321"]},
        )
        bridge = _source_record(
            conn,
            publication,
            source_id="W1",
            external_ids={"hal_id": ["hal-01234567", "hal-07654321"]},
        )

        reconcile(conn, logger)

        assert _source_record_state(conn, bridge)[0] == _source_record_state(conn, first)[0]
        assert _source_record_state(conn, second)[0] != _source_record_state(conn, first)[0]
