"""Tests d'intégration pour `infrastructure.queries.pipeline.publications_match_or_create`.

Couvre en particulier le contrat de **staleness** : les trois rattachements bulk (`bulk_link_orphans_by_doi`, `bulk_link_orphans_by_nnt`, `bulk_link_orphans_by_hal_id`) doivent bumper `source_publications.updated_at` pour que `fetch_stale_publication_ids` voie la publication comme stale et déclenche `refresh_from_sources` en Phase 2 — sinon l'agrégation cross-source (oa_status, abstract, …) ne reflète jamais la SP nouvellement rattachée.
"""

from sqlalchemy import text

from infrastructure.queries.pipeline.publications_match_or_create import (
    bulk_link_orphans_by_doi,
    bulk_link_orphans_by_hal_id,
    bulk_link_orphans_by_nnt,
    bulk_link_orphans_by_pmid,
    fetch_stale_publication_ids,
)


def _create_pub(conn, *, doi=None, title="T"):
    row = conn.execute(
        text("""
            INSERT INTO publications (title, title_normalized, pub_year, doc_type, doi)
            VALUES (:t, lower(:t), 2024, 'article'::doc_type, :doi) RETURNING id
        """),
        {"t": title, "doi": doi},
    ).one()
    return row.id


def _create_orphan_sp(conn, *, source, source_id, doi=None, external_ids=None, old_age_days=10):
    """Crée une SP orpheline (publication_id=NULL) avec `updated_at` ancien — simule le cas typique où la SP existe en base depuis un précédent run, avant rattachement."""
    row = conn.execute(
        text(f"""
            INSERT INTO source_publications
                (source, source_id, title, doi, external_ids,
                 updated_at)
            VALUES (CAST(:src AS source_type), :sid, 'T', :doi, CAST(:ext AS jsonb),
                    now() - interval '{int(old_age_days)} days')
            RETURNING id, updated_at
        """),
        {
            "src": source,
            "sid": source_id,
            "doi": doi,
            "ext": external_ids if external_ids is not None else "{}",
        },
    ).one()
    return row.id, row.updated_at


def _force_pub_updated_at(conn, pub_id, *, days_ago):
    """Force `publications.updated_at` à une date passée pour pouvoir tester la fenêtre de staleness."""
    conn.execute(
        text(
            f"UPDATE publications SET updated_at = now() - interval '{int(days_ago)} days' "
            "WHERE id = :id"
        ),
        {"id": pub_id},
    )


def _get_sp_updated_at(conn, sp_id):
    return conn.execute(
        text("SELECT updated_at FROM source_publications WHERE id = :id"),
        {"id": sp_id},
    ).scalar_one()


def _get_pub_updated_at(conn, pub_id):
    return conn.execute(
        text("SELECT updated_at FROM publications WHERE id = :id"),
        {"id": pub_id},
    ).scalar_one()


# ── bulk_link_orphans_by_doi ────────────────────────────────────────


def test_bulk_link_orphans_by_doi_bumps_sp_updated_at(sa_sync_conn):
    """Après rattachement par DOI, `sp.updated_at` doit dépasser `publications.updated_at` — sinon `fetch_stale_publication_ids` ne voit pas la publication comme stale et le refresh ne joue pas (bug du 2026-05-28 : 2117 publications avec oa_status canonique faussement 'closed'). Test de non-régression."""
    pub_id = _create_pub(sa_sync_conn, doi="10.1234/foo")
    _force_pub_updated_at(sa_sync_conn, pub_id, days_ago=1)
    sp_id, _ = _create_orphan_sp(
        sa_sync_conn, source="openalex", source_id="W1", doi="10.1234/foo", old_age_days=10
    )

    linked = bulk_link_orphans_by_doi(sa_sync_conn)

    assert linked == 1
    # SP est bien rattachée
    assert (
        sa_sync_conn.execute(
            text("SELECT publication_id FROM source_publications WHERE id = :id"),
            {"id": sp_id},
        ).scalar_one()
        == pub_id
    )
    # Contrat de staleness : sp.updated_at > pub.updated_at
    assert _get_sp_updated_at(sa_sync_conn, sp_id) > _get_pub_updated_at(sa_sync_conn, pub_id)
    # Phase 2 de match_or_create voit la pub comme stale
    assert pub_id in fetch_stale_publication_ids(sa_sync_conn)


# ── bulk_link_orphans_by_nnt ────────────────────────────────────────


def test_bulk_link_orphans_by_nnt_bumps_sp_updated_at(sa_sync_conn):
    """Après rattachement par NNT, `sp.updated_at` doit dépasser `publications.updated_at` (cf. note dans `test_bulk_link_orphans_by_doi_bumps_sp_updated_at`)."""
    pub_id = _create_pub(sa_sync_conn, title="Thèse")
    _force_pub_updated_at(sa_sync_conn, pub_id, days_ago=1)
    # Donor : SP déjà rattachée avec un NNT
    _create_orphan_sp(
        sa_sync_conn,
        source="theses",
        source_id="2024UCFA0001",
        external_ids='{"nnt": "2024UCFA0001"}',
        old_age_days=10,
    )
    sa_sync_conn.execute(
        text(
            "UPDATE source_publications SET publication_id = :pid "
            "WHERE source = 'theses' AND source_id = '2024UCFA0001'"
        ),
        {"pid": pub_id},
    )
    # Orphan à rattacher : HAL avec le même NNT en external_ids
    sp_id, _ = _create_orphan_sp(
        sa_sync_conn,
        source="hal",
        source_id="tel-001",
        external_ids='{"nnt": "2024UCFA0001"}',
        old_age_days=10,
    )

    linked = bulk_link_orphans_by_nnt(sa_sync_conn)

    assert linked == 1
    assert (
        sa_sync_conn.execute(
            text("SELECT publication_id FROM source_publications WHERE id = :id"),
            {"id": sp_id},
        ).scalar_one()
        == pub_id
    )
    assert _get_sp_updated_at(sa_sync_conn, sp_id) > _get_pub_updated_at(sa_sync_conn, pub_id)
    assert pub_id in fetch_stale_publication_ids(sa_sync_conn)


# ── bulk_link_orphans_by_hal_id ─────────────────────────────────────


def test_bulk_link_orphans_by_hal_id_bumps_sp_updated_at(sa_sync_conn):
    """Après rattachement par hal_id, `sp.updated_at` doit dépasser `publications.updated_at` (cf. note dans `test_bulk_link_orphans_by_doi_bumps_sp_updated_at`).

    Convention : `hal_id` vit dans `external_ids` sur **toutes** les sources, y compris HAL native (le normalizer pose `external_ids.hal_id = source_id`)."""
    pub_id = _create_pub(sa_sync_conn, title="Article HAL")
    _force_pub_updated_at(sa_sync_conn, pub_id, days_ago=1)
    # Donor : SP HAL native déjà rattachée, avec external_ids.hal_id posé par le normalizer
    _create_orphan_sp(
        sa_sync_conn,
        source="hal",
        source_id="hal-12345",
        external_ids='{"hal_id": ["hal-12345"]}',
        old_age_days=10,
    )
    sa_sync_conn.execute(
        text(
            "UPDATE source_publications SET publication_id = :pid "
            "WHERE source = 'hal' AND source_id = 'hal-12345'"
        ),
        {"pid": pub_id},
    )
    # Orphan à rattacher : OpenAlex avec hal_id en external_ids
    sp_id, _ = _create_orphan_sp(
        sa_sync_conn,
        source="openalex",
        source_id="W42",
        external_ids='{"hal_id": ["hal-12345"]}',
        old_age_days=10,
    )

    linked = bulk_link_orphans_by_hal_id(sa_sync_conn)

    assert linked == 1
    assert (
        sa_sync_conn.execute(
            text("SELECT publication_id FROM source_publications WHERE id = :id"),
            {"id": sp_id},
        ).scalar_one()
        == pub_id
    )
    assert _get_sp_updated_at(sa_sync_conn, sp_id) > _get_pub_updated_at(sa_sync_conn, pub_id)
    assert pub_id in fetch_stale_publication_ids(sa_sync_conn)


def test_bulk_link_orphans_by_hal_id_symmetric_orphan_hal_to_cross_source(sa_sync_conn):
    """Symétrie inverse : SP HAL orpheline rattachée à la publi d'une SP non-HAL (qui carry hal_id en external_ids). Couvert depuis que le normalizer HAL pose `external_ids.hal_id` — avant, c'était le path `link_only` de `merge_pubs_by_hal_id`."""
    pub_id = _create_pub(sa_sync_conn, title="Article HAL inverse")
    _force_pub_updated_at(sa_sync_conn, pub_id, days_ago=1)
    # Donor : OpenAlex déjà rattachée, avec hal_id en external_ids
    _create_orphan_sp(
        sa_sync_conn,
        source="openalex",
        source_id="W77",
        external_ids='{"hal_id": ["hal-XYZ"]}',
        old_age_days=10,
    )
    sa_sync_conn.execute(
        text(
            "UPDATE source_publications SET publication_id = :pid "
            "WHERE source = 'openalex' AND source_id = 'W77'"
        ),
        {"pid": pub_id},
    )
    # Orphan à rattacher : SP HAL native — external_ids.hal_id posé par le normalizer
    sp_id, _ = _create_orphan_sp(
        sa_sync_conn,
        source="hal",
        source_id="hal-XYZ",
        external_ids='{"hal_id": ["hal-XYZ"]}',
        old_age_days=10,
    )

    linked = bulk_link_orphans_by_hal_id(sa_sync_conn)

    assert linked == 1
    assert (
        sa_sync_conn.execute(
            text("SELECT publication_id FROM source_publications WHERE id = :id"),
            {"id": sp_id},
        ).scalar_one()
        == pub_id
    )


# ── bulk_link_orphans_by_pmid ───────────────────────────────────────


def test_bulk_link_orphans_by_pmid_bumps_sp_updated_at(sa_sync_conn):
    """Après rattachement par PMID, `sp.updated_at` doit dépasser `publications.updated_at` (cf. note dans `test_bulk_link_orphans_by_doi_bumps_sp_updated_at`)."""
    pub_id = _create_pub(sa_sync_conn, title="Article biomed")
    _force_pub_updated_at(sa_sync_conn, pub_id, days_ago=1)
    # Donor : SP ScanR déjà rattachée, avec external_ids.pmid
    _create_orphan_sp(
        sa_sync_conn,
        source="scanr",
        source_id="scanr-1",
        external_ids='{"pmid": "28973220"}',
        old_age_days=10,
    )
    sa_sync_conn.execute(
        text(
            "UPDATE source_publications SET publication_id = :pid "
            "WHERE source = 'scanr' AND source_id = 'scanr-1'"
        ),
        {"pid": pub_id},
    )
    # Orphan à rattacher : OpenAlex avec le même PMID en external_ids
    sp_id, _ = _create_orphan_sp(
        sa_sync_conn,
        source="openalex",
        source_id="W43",
        external_ids='{"pmid": "28973220"}',
        old_age_days=10,
    )

    linked = bulk_link_orphans_by_pmid(sa_sync_conn)

    assert linked == 1
    assert (
        sa_sync_conn.execute(
            text("SELECT publication_id FROM source_publications WHERE id = :id"),
            {"id": sp_id},
        ).scalar_one()
        == pub_id
    )
    assert _get_sp_updated_at(sa_sync_conn, sp_id) > _get_pub_updated_at(sa_sync_conn, pub_id)
    assert pub_id in fetch_stale_publication_ids(sa_sync_conn)
