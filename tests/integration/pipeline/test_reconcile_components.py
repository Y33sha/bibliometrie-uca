"""Réconciliation des enregistrements sources : voisinage direct des enregistrements sources marqués, relevé de la file, et passe complète `reconcile()` (rattachement, création, fusion et scission de publications, suppression des marquages traités)."""

import logging
from functools import partial

from sqlalchemy import bindparam, text

from domain.merge import MergedEntity
from domain.publications.reconciliation import manual_merge_tokens
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.source_records.keys import project_confirmation_keys
from infrastructure.db.doi_targets import fetch_doi_targets
from infrastructure.db.queues import Queue
from infrastructure.db.source_record_identifiers import identifiers_json_sql, parse_identifiers
from pipeline.transformation.publications.reconciliation import (
    fetch_reconciliation_universe,
    mark_for_reconciliation,
    mark_publication_siblings,
    reconcile,
    reconcile_source_records,
    snapshot_queued_source_records,
)
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.publications import insert_apc_payment
from tests.integration.helpers.queues import clear, mark, queued
from tests.integration.helpers.redirects import redirect_of
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

# Enregistrement source OpenAlex de 2024, de titre « T », article par défaut.
_source_record = partial(
    insert_source_record, source="openalex", title="T", publication_year=2024, doc_type="article"
)

logger = logging.getLogger("test_reconcile_components")

_PRIMARY, _DERIVED, _SECONDARY = (
    SourceIdentifierRole.PRIMARY,
    SourceIdentifierRole.DERIVED,
    SourceIdentifierRole.SECONDARY,
)


def _ids(id_type, role, *values):
    return [SourceIdentifier(id_type, v, role) for v in values]


def _hal(role, *values):
    return _ids(SourceIdentifierType.HAL_ID, role, *values)


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
    """Enregistre une fusion manuelle des enregistrements sources `source_record_ids`, par leur clé naturelle. Renvoie son identifiant."""
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


def _add_doi_target(conn, doi, target_doi) -> None:
    conn.execute(
        text(
            "INSERT INTO doi_targets (doi, target_doi, rule)"
            " VALUES (:doi, :target, 'DATACITE_VERSION_TO_CONCEPT')"
        ),
        {"doi": doi, "target": target_doi},
    )


def _universe(conn) -> set[int]:
    """Relève la file, puis renvoie les identifiants du voisinage direct des enregistrements sources marqués."""
    snapshot_queued_source_records(conn)
    return {r.id for r in fetch_reconciliation_universe(conn)}


class TestUniverse:
    def test_fetches_dirty_and_one_hop_neighbor(self, sa_sync_conn):
        """Le voisinage contient l'enregistrement source marqué et l'enregistrement source non marqué qui partage son DOI, sans l'enregistrement source sans clé commune. Seuls les enregistrements sources ont le DOI : deux publications ne peuvent avoir le même DOI."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        unrelated_publication = _seed_publication(conn)
        dirty = _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        neighbor = _source_record(conn, publication_b, source_id="b", doi="10.1/x", marked=False)
        _source_record(conn, unrelated_publication, source_id="c", doi="10.9/z", marked=False)

        assert _universe(conn) == {dirty, neighbor}

    def test_neighbor_by_doi_target(self, sa_sync_conn):
        """Le DOI d'une version a pour cible celui du concept : les enregistrements sources des deux DOI sont voisins."""
        conn = sa_sync_conn
        _add_doi_target(conn, "10.5281/zenodo.101", "10.5281/zenodo.100")
        dirty = _source_record(conn, source_id="hal", doi="10.5281/zenodo.101")
        concept = _source_record(conn, source_id="c", doi="10.5281/zenodo.100", marked=False)
        version = _source_record(conn, source_id="v", doi="10.5281/zenodo.101", marked=False)

        assert _universe(conn) == {dirty, concept, version}
        clear(conn, Queue.SOURCE_RECORD_KEYS)
        mark(conn, Queue.SOURCE_RECORD_KEYS, [concept])
        assert _universe(conn) == {dirty, concept, version}

    def test_neighbor_by_hal_id(self, sa_sync_conn):
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        dirty = _source_record(
            conn,
            publication_a,
            source="hal",
            source_id="hal-01000001",
            identifiers=_hal(_PRIMARY, "hal-01000001"),
        )
        neighbor = _source_record(
            conn,
            publication_b,
            source_id="b",
            marked=False,
            identifiers=_hal(_SECONDARY, "hal-01000001", "hal-01000002"),
        )
        assert _universe(conn) == {dirty, neighbor}

    def test_hal_id_after_the_key_is_not_a_neighbor(self, sa_sync_conn):
        """La clé HAL d'un enregistrement source est son premier `hal_id` par rôle puis par valeur : les suivants ne relient rien."""
        conn = sa_sync_conn
        dirty = _source_record(
            conn,
            source="hal",
            source_id="hal-01000002",
            identifiers=_hal(_PRIMARY, "hal-01000002"),
        )
        _source_record(
            conn,
            source_id="b",
            marked=False,
            identifiers=_hal(_SECONDARY, "hal-01000001", "hal-01000002"),
        )
        assert _universe(conn) == {dirty}

    def test_derived_hal_id_is_the_key(self, sa_sync_conn):
        conn = sa_sync_conn
        dirty = _source_record(
            conn,
            source="hal",
            source_id="hal-01000002",
            identifiers=_hal(_PRIMARY, "hal-01000002"),
        )
        neighbor = _source_record(
            conn,
            source_id="b",
            marked=False,
            identifiers=[*_hal(_SECONDARY, "hal-01000001"), *_hal(_DERIVED, "hal-01000002")],
        )
        assert _universe(conn) == {dirty, neighbor}

    def test_removed_hal_id_is_not_a_neighbor(self, sa_sync_conn):
        conn = sa_sync_conn
        removed = SourceIdentifier(
            SourceIdentifierType.HAL_ID,
            "hal-01000001",
            _SECONDARY,
            "HAL_DEPOSIT_MISSING_TO_REMOVED",
        )
        dirty = _source_record(conn, source_id="a", identifiers=[removed])
        _source_record(
            conn,
            source="hal",
            source_id="hal-01000001",
            marked=False,
            identifiers=_hal(_PRIMARY, "hal-01000001"),
        )
        assert _universe(conn) == {dirty}

    def test_neighbor_by_metadata_block(self, sa_sync_conn):
        """Voisinage par bloc de métadonnées : deux thèses de même type, même titre long et même année, sans identifiant commun."""
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
            identifiers=_hal(_PRIMARY, "hal-04263452"),
            marked=False,
        )
        _source_record(conn, _seed_publication(conn), source_id="c", marked=False)
        _manual_merge(conn, [dirty, neighbor])

        assert _universe(conn) == {dirty, neighbor}

    def test_dirty_orphan_included(self, sa_sync_conn):
        """Un enregistrement source orphelin marqué entre dans la passe : la réconciliation le rattache, crée sa publication ou l'écarte."""
        conn = sa_sync_conn
        orphan = _source_record(conn, source_id="orphan", doi="10.1/x")
        assert snapshot_queued_source_records(conn) == [orphan]


class TestEndToEnd:
    def test_two_publications_sharing_doi_merged(self, sa_sync_conn):
        """Deux publications dont les enregistrements sources partagent un DOI sont fusionnées. Aucune des deux n'a le DOI : l'ancre est la publication du plus petit enregistrement source."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        source_record_a = _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        source_record_b = _source_record(conn, publication_b, source_id="b", doi="10.1/x")

        reconcile(conn, logger)

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

    def test_scanr_record_joins_the_article_of_its_derived_doi(self, sa_sync_conn):
        """L'identifiant ScanR désigne l'article ; le premier DOI de ses `externalIds` est celui du preprint.

        Régression : l'enregistrement source ScanR rejoignait la publication du preprint par le DOI de la colonne."""
        conn = sa_sync_conn
        article = _seed_publication(conn, doi="10.1/article")
        preprint = _seed_publication(conn, doi="10.1101/preprint")
        _source_record(conn, article, source="crossref", source_id="a", doi="10.1/article")
        _source_record(conn, preprint, source="crossref", source_id="p", doi="10.1101/preprint")
        scanr = _source_record(
            conn,
            preprint,
            source="scanr",
            source_id="doi10.1/article",
            doi="10.1101/preprint",
            identifiers=[
                *_ids(SourceIdentifierType.DOI, _DERIVED, "10.1/article"),
                *_ids(SourceIdentifierType.DOI, _SECONDARY, "10.1101/preprint"),
            ],
        )

        reconcile(conn, logger)

        assert _source_record_state(conn, scanr)[0] == article

    def test_deposit_with_a_version_doi_joins_the_concept_publication(self, sa_sync_conn):
        """Régression : un dépôt HAL au DOI d'une version Zenodo était écarté de la réconciliation avec la version.

        Le DOI de la version a pour cible le concept : le dépôt HAL rejoint la publication du concept, qui garde le DOI du concept. L'enregistrement DataCite de la version, écarté, reste orphelin."""
        conn = sa_sync_conn
        _add_doi_target(conn, "10.5281/zenodo.101", "10.5281/zenodo.100")
        publication = _seed_publication(conn, doi="10.5281/zenodo.100")
        concept = _source_record(
            conn, publication, source="datacite", source_id="c", doi="10.5281/zenodo.100"
        )
        version = _source_record(
            conn, source="datacite", source_id="v", doi="10.5281/zenodo.101", is_matchable=False
        )
        hal = _source_record(conn, source="hal", source_id="hal-1", doi="10.5281/zenodo.101")

        reconcile(conn, logger)

        assert _source_record_state(conn, concept)[0] == publication
        assert _source_record_state(conn, hal)[0] == publication
        assert _source_record_state(conn, version)[0] is None
        assert (
            conn.execute(
                text("SELECT doi FROM publications WHERE id = :id"), {"id": publication}
            ).scalar_one()
            == "10.5281/zenodo.100"
        )

    def test_publication_of_excluded_records_only_is_deleted(self, sa_sync_conn):
        """Régression : une publication faite de copies GRESIS (DOI 10.60692) est supprimée, ses enregistrements sources restent orphelins."""
        conn = sa_sync_conn
        publication = _seed_publication(conn)
        gresis = partial(_source_record, doi="10.60692/m2raz-tjw54", is_matchable=False)
        openalex = gresis(conn, publication, source_id="a")
        datacite = gresis(conn, publication, source="datacite", source_id="b")

        stats = reconcile(conn, logger)

        assert not _publication_exists(conn, publication)
        assert _source_record_state(conn, openalex) == (None, False)
        assert _source_record_state(conn, datacite) == (None, False)
        assert stats.detached == 2

    def test_merged_publication_with_excluded_record_hands_over_to_successor(self, sa_sync_conn):
        """La publication absorbée perd aussi un enregistrement source de paratexte. Elle est dissoute : ses paiements APC et son identifiant passent à l'ancre."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn)
        publication_b = _seed_publication(conn)
        payment = insert_apc_payment(conn, publication_id=publication_b, open_access_fee=True)
        paratext = _source_record(
            conn,
            publication_b,
            source_id="c",
            title="Index",
            title_normalized="index",
            is_matchable=False,
        )
        source_record_a = _source_record(conn, publication_a, source_id="a", doi="10.1/x")
        source_record_b = _source_record(conn, publication_b, source_id="b", doi="10.1/x")

        reconcile(conn, logger)

        assert _source_record_state(conn, paratext) == (None, False)
        assert _source_record_state(conn, source_record_a)[0] == publication_a
        assert _source_record_state(conn, source_record_b)[0] == publication_a
        assert not _publication_exists(conn, publication_b)
        assert redirect_of(conn, MergedEntity.PUBLICATION, publication_b) == publication_a
        assert (
            conn.execute(
                text("SELECT publication_id FROM apc_payments WHERE id = :id"), {"id": payment}
            ).scalar_one()
            == publication_a
        )

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
        """Une publication de DOI X contient un enregistrement source de DOI Y, relié par un hal-id : l'enregistrement source de DOI X garde la publication, celui de DOI Y passe dans une publication créée."""
        conn = sa_sync_conn
        publication = _seed_publication(conn, doi="10.1/x")
        source_record_x = _source_record(
            conn,
            publication,
            source_id="x",
            doi="10.1/x",
            identifiers=_hal(_SECONDARY, "hal-01000009"),
        )
        source_record_y = _source_record(
            conn,
            publication,
            source_id="y",
            doi="10.2/y",
            identifiers=_hal(_SECONDARY, "hal-01000009"),
        )

        reconcile(conn, logger)

        assert _source_record_state(conn, source_record_x) == (publication, False)
        y_publication, y_dirty = _source_record_state(conn, source_record_y)
        assert y_publication != publication
        assert y_dirty is False
        assert _publication_exists(conn, publication)
        assert _publication_exists(conn, y_publication)

    def test_two_theses_sharing_title_year_merged(self, sa_sync_conn):
        """Deux thèses de sources différentes, de même titre long et même année, sans DOI, NNT ni hal-id commun, sont fusionnées par bloc de métadonnées."""
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
        """Deux publications de DOI distincts qui partagent un hal-id restent séparées : deux DOI distincts interdisent la fusion."""
        conn = sa_sync_conn
        publication_a = _seed_publication(conn, doi="10.1/x")
        publication_b = _seed_publication(conn, doi="10.2/y")
        hal_id = _hal(_SECONDARY, "hal-01000001")
        source_record_a = _source_record(
            conn, publication_a, source_id="a", doi="10.1/x", identifiers=hal_id
        )
        source_record_b = _source_record(
            conn, publication_b, source_id="b", doi="10.2/y", identifiers=hal_id
        )

        reconcile(conn, logger)

        assert _publication_exists(conn, publication_a)
        assert _publication_exists(conn, publication_b)
        # Sans fusion, les enregistrements sources réconciliés quittent la file.
        assert _source_record_state(conn, source_record_a)[1] is False
        assert _source_record_state(conn, source_record_b)[1] is False

    def test_publication_of_a_residual_source_record_is_refreshed(self, sa_sync_conn):
        """Régression : l'enregistrement source sans DOI d'une composante à deux DOI reste sur sa publication, qui gardait le DOI qu'il avait perdu."""
        conn = sa_sync_conn
        hal_id = _hal(_SECONDARY, "hal-01234567")
        stale = _seed_publication(conn, doi="10.9/retire")
        residual = _source_record(conn, stale, source_id="a", identifiers=hal_id)
        for source_id, doi in (("b", "10.1/x"), ("c", "10.2/y")):
            _source_record(
                conn,
                _seed_publication(conn, doi=doi),
                source_id=source_id,
                doi=doi,
                marked=False,
                identifiers=hal_id,
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
            identifiers=_hal(_PRIMARY, "hal-04263452"),
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
            identifiers=_hal(_PRIMARY, "hal-04263452"),
            marked=False,
        )
        sibling = _source_record(
            conn,
            without_doi,
            source_id="W1",
            identifiers=_hal(_DERIVED, "hal-04263452"),
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
        """Deux communications de sources différentes, de même titre long et même année, sans DOI, sont fusionnées par bloc de métadonnées."""
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
        """Un titre court, sous le seuil de longueur, est exclu du bloc de métadonnées : pas de fusion."""
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
        """Même titre long et même année, mais types différents : pas de fusion, le type fait partie du bloc."""
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
    """Marquage pour la réconciliation, total ou ciblé, utilisé par le script de maintenance et l'option `rebuild`."""

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
        assert _source_record_state(conn, source_record)[1] is False  # rien d'écrit en simulation


class TestUniverseMatchesPythonTokens:
    """Le voisinage SQL relie exactement les enregistrements sources que relient les tokens Python (`project_confirmation_keys`), garde de longueur du bloc de métadonnées comprise.

    Chaque enregistrement source est marqué seul ; son voisinage SQL est comparé aux enregistrements sources dont les tokens Python ont une intersection avec les siens.
    """

    def test_sql_universe_matches_python_token_linkage(self, sa_sync_conn_owner):
        conn = sa_sync_conn_owner
        long_a, long_b = "a" * 40, "b" * 40
        len30 = "c" * 30  # au seuil : pas de bloc de métadonnées, qui exige plus de 30 caractères
        _add_doi_target(conn, "10.5281/zenodo.101", "10.5281/zenodo.100")
        ids = [
            _source_record(conn, source_id="doi1", doi="10.1/x", marked=False),
            _source_record(conn, source_id="doi2", doi="10.1/x", marked=False),
            # Le DOI d'une version a pour cible celui du concept.
            _source_record(conn, source_id="version", doi="10.5281/zenodo.101", marked=False),
            _source_record(conn, source_id="concept", doi="10.5281/zenodo.100", marked=False),
            # DOI secondaires : la copie d'archive relie `work` à l'article.
            _source_record(
                conn,
                source_id="work",
                marked=False,
                identifiers=_ids(SourceIdentifierType.DOI, _SECONDARY, "10.1/x", "10.9/copie"),
            ),
            # hal-00000002 est la clé de hal2, pas celle de hal1 : les deux restent séparés.
            _source_record(
                conn,
                source_id="hal1",
                marked=False,
                identifiers=_hal(_SECONDARY, "hal-00000001", "hal-00000002"),
            ),
            _source_record(
                conn,
                source_id="hal2",
                marked=False,
                identifiers=_hal(_SECONDARY, "hal-00000002", "hal-00000003"),
            ),
            # Hal-id à préfixe de collection institutionnelle : le value object `HALId` l'accepte comme token, comme le SQL. Le numéro a 8 chiffres, comme l'exige `HALId`.
            _source_record(
                conn,
                source_id="emse1",
                marked=False,
                identifiers=_hal(_SECONDARY, "emse-04836977"),
            ),
            _source_record(
                conn,
                source_id="emse2",
                marked=False,
                identifiers=_hal(_DERIVED, "emse-04836977"),
            ),
            _source_record(
                conn,
                source_id="nnt1",
                marked=False,
                identifiers=_ids(SourceIdentifierType.NNT, _SECONDARY, "2024UCA01"),
            ),
            _source_record(
                conn,
                source_id="nnt2",
                marked=False,
                identifiers=_ids(SourceIdentifierType.NNT, _PRIMARY, "2024UCA01"),
            ),
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
                    f"SELECT id, {identifiers_json_sql('id')} AS identifiers, doc_type,"
                    " title_normalized, publication_year FROM source_records WHERE id = ANY(:ids)"
                ).bindparams(bindparam("ids")),
                {"ids": ids},
            )
        }
        identifiers = {i: parse_identifiers(r.identifiers) for i, r in rows.items()}
        doi_targets = fetch_doi_targets(conn, (x for ids_ in identifiers.values() for x in ids_))
        toks = {
            i: project_confirmation_keys(
                identifiers[i],
                r.doc_type,
                r.title_normalized,
                r.publication_year,
                doi_targets,
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
    """Régression : une publication sans enregistrement source, avec un DOI, faisait échouer la réconciliation. Les enregistrements sources de ce DOI s'y rattachent ; une publication créée aurait le même DOI."""

    def test_orphan_publication_with_doi_is_reused_not_duplicated(self, sa_sync_conn):
        conn = sa_sync_conn
        orphan_publication = _seed_publication(
            conn, doi="10.70675/abc"
        )  # DOI, sans enregistrement source
        sp1 = _source_record(conn, source_id="t1", title_normalized="t", doi="10.70675/abc")
        sp2 = _source_record(conn, source_id="t2", doi="10.70675/abc")
        # Avec une contribution source du périmètre, ces orphelins créeraient une publication au DOI déjà pris (`publications_doi_lower_key`).
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
    """Régression : un enregistrement source restait sur une publication après la disparition de la clé qui l'y rattachait.

    Exemple : une préversion arXiv rejoint la publication tant que l'enregistrement OpenAlex a le DOI de la préversion, puis OpenAlex donne le DOI de la version publiée. Le voisinage se calcule sur les clés à jour, sans la préversion. Seul le marquage des autres enregistrements sources de la publication la fait entrer dans la passe ; sans lui, la publication garde deux DOI distincts.
    """

    PREPRINT_DOI = "10.48550/arxiv.2409.20505"
    PUBLISHED_DOI = "10.1016/j.tcs.2026.116186"

    def _seed_drifted_pair(self, conn) -> tuple[int, int, int]:
        """Une publication au DOI de la préversion, et ses deux enregistrements sources sans clé commune : DOI distincts, aucun identifiant commun, titres absents."""
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
        """Seuls les autres enregistrements sources de la publication sont marqués, à l'exclusion de ceux d'une autre publication et des orphelins."""
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
        # L'ancre est l'enregistrement source du DOI de la publication : la publication reste à la préversion.
        assert preprint_publication == publication
        assert (preprint_dirty, published_dirty) == (False, False)
        assert _distinct_dois(conn, preprint_publication) == {self.PREPRINT_DOI}
        assert _distinct_dois(conn, published_publication) == {self.PUBLISHED_DOI}


class TestFirstHalIdKey:
    """Un enregistrement source qui cite deux dépôts HAL rejoint la publication de sa clé HAL, le premier `hal_id` par rôle puis par valeur, et laisse les deux dépôts distincts."""

    def test_bridge_source_record_joins_its_key_deposit_only(self, sa_sync_conn):
        conn = sa_sync_conn
        publication = _seed_publication(conn)
        first = _source_record(
            conn,
            publication,
            source="hal",
            source_id="hal-01234567",
            doc_type="conference_paper",
            identifiers=_hal(_PRIMARY, "hal-01234567"),
        )
        second = _source_record(
            conn,
            publication,
            source="hal",
            source_id="hal-07654321",
            doc_type="book_chapter",
            identifiers=_hal(_PRIMARY, "hal-07654321"),
        )
        bridge = _source_record(
            conn,
            publication,
            source_id="W1",
            identifiers=_hal(_SECONDARY, "hal-01234567", "hal-07654321"),
        )

        reconcile(conn, logger)

        assert _source_record_state(conn, bridge)[0] == _source_record_state(conn, first)[0]
        assert _source_record_state(conn, second)[0] != _source_record_state(conn, first)[0]
