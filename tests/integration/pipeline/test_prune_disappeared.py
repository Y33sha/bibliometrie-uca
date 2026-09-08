"""Retrait des documents marqués disparus.

Un `staging` portant `disappeared_at` perd ses `source_publications`, et celles-ci emportent leurs `source_authorships` par cascade. La ligne de `staging` reste, avec sa marque.
"""

from sqlalchemy import text

from infrastructure.pipeline.normalize.staging import delete_disappeared_source_publications


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


def _source_publication(conn, staging_id: int, source_id: str) -> int:
    return conn.execute(
        text("""
            INSERT INTO source_publications (source, source_id, staging_id, title)
            VALUES ('hal', :sid, :stg, 'Titre')
            RETURNING id
        """),
        {"sid": source_id, "stg": staging_id},
    ).scalar_one()


def _signature(conn, source_publication_id: int) -> None:
    identity_id = conn.execute(
        text("""
            INSERT INTO author_identifying_keys (author_name_normalized)
            VALUES ('dupont jean') RETURNING id
        """)
    ).scalar_one()
    conn.execute(
        text("""
            INSERT INTO source_authorships
                (source, source_publication_id, author_position, raw_author_name, identity_id)
            VALUES ('hal', :sp, 0, 'Dupont, Jean', :iid)
        """),
        {"sp": source_publication_id, "iid": identity_id},
    )


def test_le_document_disparu_perd_sa_publication_source(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, "hal-disparu", disparu=True)
    sp_id = _source_publication(sa_sync_conn_owner, staging_id, "hal-disparu")

    assert delete_disappeared_source_publications(sa_sync_conn_owner) == 1

    reste = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_publications WHERE id = :id"), {"id": sp_id}
    ).scalar_one()
    assert reste == 0


def test_les_signatures_suivent_par_cascade(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, "hal-avec-signature", disparu=True)
    sp_id = _source_publication(sa_sync_conn_owner, staging_id, "hal-avec-signature")
    _signature(sa_sync_conn_owner, sp_id)

    delete_disappeared_source_publications(sa_sync_conn_owner)

    restantes = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_authorships WHERE source_publication_id = :id"),
        {"id": sp_id},
    ).scalar_one()
    assert restantes == 0


def test_le_document_encore_rendu_est_laisse(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, "hal-present", disparu=False)
    sp_id = _source_publication(sa_sync_conn_owner, staging_id, "hal-present")

    delete_disappeared_source_publications(sa_sync_conn_owner)

    reste = sa_sync_conn_owner.execute(
        text("SELECT count(*) FROM source_publications WHERE id = :id"), {"id": sp_id}
    ).scalar_one()
    assert reste == 1


def test_la_ligne_de_staging_reste_avec_sa_marque(sa_sync_conn_owner):
    staging_id = _staging(sa_sync_conn_owner, "hal-trace", disparu=True)
    _source_publication(sa_sync_conn_owner, staging_id, "hal-trace")

    delete_disappeared_source_publications(sa_sync_conn_owner)

    marque = sa_sync_conn_owner.execute(
        text("SELECT disappeared_at IS NOT NULL FROM staging WHERE id = :id"), {"id": staging_id}
    ).scalar_one()
    assert marque is True


def test_le_second_passage_ne_retire_rien(sa_sync_conn_owner):
    """Balayage idempotent : rien ne subsiste à retirer au passage suivant."""
    staging_id = _staging(sa_sync_conn_owner, "hal-idempotent", disparu=True)
    _source_publication(sa_sync_conn_owner, staging_id, "hal-idempotent")

    assert delete_disappeared_source_publications(sa_sync_conn_owner) == 1
    assert delete_disappeared_source_publications(sa_sync_conn_owner) == 0
