"""L'entité `Publication` enregistre et relit ses indicateurs de citation."""

from pipeline.transformation.publications.store import PublicationStore


def test_indicateurs_enregistres_puis_relus(sa_sync_conn):
    store = PublicationStore(sa_sync_conn)
    publication_id = store.create(
        title="t",
        title_normalized="t",
        doc_type="article",
        publication_year=2024,
        doi=None,
        oa_status="gold",
    )
    publication = store.find_by_id(publication_id)
    assert publication is not None
    publication.impact = {"cited_by_count": 40, "fwci": 2.1, "top_10_percent": True}
    store.save([publication])

    relue = store.find_by_id(publication_id)
    assert relue is not None
    assert relue.impact == {"cited_by_count": 40, "fwci": 2.1, "top_10_percent": True}
