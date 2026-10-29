"""L'agrégat `Publication` enregistre et relit sa licence et celle de son dépôt."""

from pipeline.transformation.publications.store import PublicationStore


def test_licences_enregistrees_puis_relues(sa_sync_conn):
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
    publication.license, publication.deposit_license = "cc-by", "repository-distribution"
    store.save(publication)

    relue = store.find_by_id(publication_id)
    assert relue is not None
    assert (relue.license, relue.deposit_license) == ("cc-by", "repository-distribution")
