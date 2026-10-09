"""Retrait des documents marqués disparus.

Un `staging` portant `disappeared_at` perd ses `source_publications`, et celles-ci emportent leurs `source_authorships` par cascade. La ligne de `staging` reste, avec sa marque.
"""

from functools import partial
from unittest.mock import MagicMock

from sqlalchemy import text

from infrastructure.pipeline.normalize.staging import (
    PgStagingQueries,
    delete_disappeared_source_publications,
)
from infrastructure.repositories import publication_repository
from tests.integration.helpers.sources import insert_signature, insert_source_publication

# Notice de titre « Titre », aux clés à jour.
_notice = partial(insert_source_publication, title="Titre", keys_dirty=False)


def _publication(conn) -> int:
    return publication_repository(conn).create(
        title="T",
        title_normalized="t",
        doc_type="article",
        pub_year=2024,
        doi=None,
        oa_status="unknown",
    )


def _a_reconcilier(conn, source_publication_id: int) -> bool:
    return conn.execute(
        text("SELECT keys_dirty FROM source_publications WHERE id = :id"),
        {"id": source_publication_id},
    ).scalar_one()


def _staging(conn, source_id: str, *, disparu: bool) -> int:
    return conn.execute(
        text("""
            INSERT INTO staging (source, source_id, raw_data, processed, disappeared_at)
            VALUES ('hal', :sid, '{}'::jsonb, TRUE,
                    CASE WHEN :dis THEN now() ELSE NULL END)
            RETURNING id
        """),
        {"sid": source_id, "dis": disparu},
    ).scalar_one()


def _signature(conn, source_publication_id: int) -> None:
    insert_signature(
        conn,
        source_publication_id,
        raw_author_name="Dupont, Jean",
        author_name_normalized="jean dupont",
    )


def test_le_document_disparu_perd_sa_publication_source(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, "hal-disparu", disparu=True)
    sp_id = _notice(sa_sync_conn_owner, source_id="hal-disparu", staging_id=staging_id)

    assert delete_disappeared_source_publications(sa_sync_conn_owner) == 1

    reste = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_publications WHERE id = :id"), {"id": sp_id}
    ).scalar_one()
    assert reste == 0


def test_les_signatures_suivent_par_cascade(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, "hal-avec-signature", disparu=True)
    sp_id = _notice(sa_sync_conn_owner, source_id="hal-avec-signature", staging_id=staging_id)
    _signature(sa_sync_conn_owner, sp_id)

    delete_disappeared_source_publications(sa_sync_conn_owner)

    restantes = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_authorships WHERE source_publication_id = :id"),
        {"id": sp_id},
    ).scalar_one()
    assert restantes == 0


def test_les_soeurs_du_document_disparu_sont_a_reconcilier(sa_sync_conn_owner):
    """La publication perd une source : ses autres sources la font réconcilier et rafraîchir."""
    conn = sa_sync_conn_owner
    publication = _publication(conn)
    _notice(
        conn,
        publication,
        source_id="hal-disparu",
        staging_id=_staging(conn, "hal-disparu", disparu=True),
    )
    soeur = _notice(
        conn,
        publication,
        source_id="hal-soeur",
        staging_id=_staging(conn, "hal-soeur", disparu=False),
    )
    etrangere = _notice(
        conn,
        _publication(conn),
        source_id="hal-autre",
        staging_id=_staging(conn, "hal-autre", disparu=False),
    )
    orpheline = _notice(
        conn, source_id="hal-seule", staging_id=_staging(conn, "hal-seule", disparu=False)
    )

    delete_disappeared_source_publications(conn)

    assert _a_reconcilier(conn, soeur) is True
    assert _a_reconcilier(conn, etrangere) is False
    assert _a_reconcilier(conn, orpheline) is False


def test_le_document_encore_rendu_est_laisse(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, "hal-present", disparu=False)
    sp_id = _notice(sa_sync_conn_owner, source_id="hal-present", staging_id=staging_id)

    delete_disappeared_source_publications(sa_sync_conn_owner)

    reste = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_publications WHERE id = :id"), {"id": sp_id}
    ).scalar_one()
    assert reste == 1


def test_la_ligne_de_staging_reste_avec_sa_marque(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, "hal-trace", disparu=True)
    _notice(sa_sync_conn_owner, source_id="hal-trace", staging_id=staging_id)

    delete_disappeared_source_publications(sa_sync_conn_owner)

    marque = sa_sync_conn_owner.execute(
        text("SELECT disappeared_at IS NOT NULL FROM staging WHERE id = :id"), {"id": staging_id}
    ).scalar_one()
    assert marque is True


def test_le_second_passage_ne_retire_rien(sa_sync_conn_owner):
    """Balayage idempotent : rien ne subsiste à retirer au passage suivant."""
    staging_id = _staging(sa_sync_conn_owner, "hal-idempotent", disparu=True)
    _notice(sa_sync_conn_owner, source_id="hal-idempotent", staging_id=staging_id)

    assert delete_disappeared_source_publications(sa_sync_conn_owner) == 1
    assert delete_disappeared_source_publications(sa_sync_conn_owner) == 0


def test_une_notice_sans_metadonnees_minimales_perd_son_enregistrement(sa_sync_conn_owner):
    """Une notice renormalisée sans année supprime l'enregistrement qu'elle avait produit, et seul celui-là ; ses frères sont marqués à réconcilier."""
    pub = _publication(sa_sync_conn_owner)
    staging_id = _staging(sa_sync_conn_owner, "W3131333980", disparu=False)
    sp_id = _notice(sa_sync_conn_owner, pub, source_id="W3131333980", staging_id=staging_id)
    autre_staging = _staging(sa_sync_conn_owner, "hal-soeur", disparu=False)
    soeur = _notice(sa_sync_conn_owner, pub, source_id="hal-soeur", staging_id=autre_staging)

    PgStagingQueries(raw_store=MagicMock()).discard_source_publication(
        sa_sync_conn_owner, staging_id
    )

    restants = (
        sa_sync_conn_owner.execute(
            text("SELECT id FROM source_publications WHERE id IN (:a, :b)"),
            {"a": sp_id, "b": soeur},
        )
        .scalars()
        .all()
    )
    assert restants == [soeur]
    assert _a_reconcilier(sa_sync_conn_owner, soeur)
