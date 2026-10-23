"""Retrait des documents marqués disparus.

Un `staging` portant `disappeared_at` perd ses `source_records`, et celles-ci emportent leurs `source_contributions` par cascade. La ligne de `staging` reste, avec sa marque.
"""

from functools import partial
from unittest.mock import MagicMock

from sqlalchemy import text

from infrastructure.db.queues import Queue
from pipeline.ingestion.common.source_records import delete_disappeared_source_records
from pipeline.ingestion.common.staging import StagingStore
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record
from tests.integration.helpers.staging import insert_staging

# Ligne de staging HAL traitée.
_staging = partial(insert_staging, processed=True)

# Enregistrement source de titre « Titre », aux clés à jour.
_source_record = partial(insert_source_record, title="Titre", keys_dirty=False)


def _publication(conn) -> int:
    return PublicationStore(conn).create(
        title="T",
        title_normalized="t",
        doc_type="article",
        publication_year=2024,
        doi=None,
        oa_status="unknown",
    )


def _a_reconcilier(conn, source_record_id: int) -> bool:
    return conn.execute(
        text("SELECT keys_dirty FROM source_records WHERE id = :id"),
        {"id": source_record_id},
    ).scalar_one()


def _source_contribution(conn, source_record_id: int) -> None:
    insert_source_contribution(
        conn,
        source_record_id,
        raw_author_name="Dupont, Jean",
        author_name_normalized="jean dupont",
    )


def test_le_document_disparu_perd_sa_publication_source(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, source_id="hal-disparu", disappeared=True)
    source_record_id = _source_record(
        sa_sync_conn_owner, source_id="hal-disparu", staging_id=staging_id
    )

    assert delete_disappeared_source_records(sa_sync_conn_owner) == 1

    reste = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()
    assert reste == 0


def test_les_contributions_sources_suivent_par_cascade(sa_sync_conn_owner):
    staging_id = _staging(
        sa_sync_conn_owner, source_id="hal-avec-contribution source", disappeared=True
    )
    source_record_id = _source_record(
        sa_sync_conn_owner, source_id="hal-avec-contribution source", staging_id=staging_id
    )
    _source_contribution(sa_sync_conn_owner, source_record_id)

    delete_disappeared_source_records(sa_sync_conn_owner)

    restantes = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_contributions WHERE source_record_id = :id"),
        {"id": source_record_id},
    ).scalar_one()
    assert restantes == 0


def test_les_soeurs_du_document_disparu_sont_a_reconcilier(sa_sync_conn_owner):
    """La publication perd une source : ses autres sources la font réconcilier et rafraîchir."""
    conn = sa_sync_conn_owner
    publication = _publication(conn)
    _source_record(
        conn,
        publication,
        source_id="hal-disparu",
        staging_id=_staging(conn, source_id="hal-disparu", disappeared=True),
    )
    soeur = _source_record(
        conn,
        publication,
        source_id="hal-soeur",
        staging_id=_staging(conn, source_id="hal-soeur"),
    )
    etrangere = _source_record(
        conn,
        _publication(conn),
        source_id="hal-autre",
        staging_id=_staging(conn, source_id="hal-autre"),
    )
    orpheline = _source_record(
        conn, source_id="hal-seule", staging_id=_staging(conn, source_id="hal-seule")
    )

    delete_disappeared_source_records(conn)

    assert _a_reconcilier(conn, soeur) is True
    assert _a_reconcilier(conn, etrangere) is False
    assert _a_reconcilier(conn, orpheline) is False


def test_la_publication_de_l_enregistrement_source_disparu_regroupe_ses_contributions_sources(
    sa_sync_conn_owner,
):
    conn = sa_sync_conn_owner
    publication = _publication(conn)
    autre = _publication(conn)
    _source_record(
        conn,
        publication,
        source_id="hal-disparu",
        staging_id=_staging(conn, source_id="hal-disparu", disappeared=True),
    )
    _source_record(
        conn, autre, source_id="hal-autre", staging_id=_staging(conn, source_id="hal-autre")
    )
    clear(conn, Queue.PUBLICATION_CONTRIBUTIONS)

    delete_disappeared_source_records(conn)

    assert queued(conn, Queue.PUBLICATION_CONTRIBUTIONS) == {publication}


def test_le_document_encore_rendu_est_laisse(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, source_id="hal-present")
    source_record_id = _source_record(
        sa_sync_conn_owner, source_id="hal-present", staging_id=staging_id
    )

    delete_disappeared_source_records(sa_sync_conn_owner)

    reste = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_records WHERE id = :id"), {"id": source_record_id}
    ).scalar_one()
    assert reste == 1


def test_la_ligne_de_staging_reste_avec_sa_marque(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, source_id="hal-trace", disappeared=True)
    _source_record(sa_sync_conn_owner, source_id="hal-trace", staging_id=staging_id)

    delete_disappeared_source_records(sa_sync_conn_owner)

    marque = sa_sync_conn_owner.execute(
        text("SELECT disappeared_at IS NOT NULL FROM staging WHERE id = :id"), {"id": staging_id}
    ).scalar_one()
    assert marque is True


def test_le_second_passage_ne_retire_rien(sa_sync_conn_owner):
    """Balayage idempotent : rien ne subsiste à retirer au passage suivant."""
    staging_id = _staging(sa_sync_conn_owner, source_id="hal-idempotent", disappeared=True)
    _source_record(sa_sync_conn_owner, source_id="hal-idempotent", staging_id=staging_id)

    assert delete_disappeared_source_records(sa_sync_conn_owner) == 1
    assert delete_disappeared_source_records(sa_sync_conn_owner) == 0


def test_un_enregistrement_source_sans_metadonnees_minimales_est_supprime(sa_sync_conn_owner):
    """Un enregistrement moissonné, renormalisé sans année, supprime l'enregistrement source qu'il avait produit, et seul celui-là ; ses frères sont marqués à réconcilier."""
    publication = _publication(sa_sync_conn_owner)
    staging_id = _staging(sa_sync_conn_owner, source_id="W3131333980")
    source_record_id = _source_record(
        sa_sync_conn_owner, publication, source_id="W3131333980", staging_id=staging_id
    )
    autre_staging = _staging(sa_sync_conn_owner, source_id="hal-soeur")
    soeur = _source_record(
        sa_sync_conn_owner, publication, source_id="hal-soeur", staging_id=autre_staging
    )

    StagingStore(sa_sync_conn_owner, raw_store=MagicMock()).discard_source_record(staging_id)

    restants = (
        sa_sync_conn_owner.execute(
            text("SELECT id FROM source_records WHERE id IN (:a, :b)"),
            {"a": source_record_id, "b": soeur},
        )
        .scalars()
        .all()
    )
    assert restants == [soeur]
    assert _a_reconcilier(sa_sync_conn_owner, soeur)
