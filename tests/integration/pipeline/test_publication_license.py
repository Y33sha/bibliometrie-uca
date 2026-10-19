"""Intégration : l'agrégat Publication enregistre et relit sa licence et la licence de son dépôt."""

from pipeline.transformation.publications.store import PublicationStore


def test_licences_enregistrees_puis_relues(sa_sync_conn):
    store = PublicationStore(sa_sync_conn)
    pub_id = store.create(
        title="t",
        title_normalized="t",
        doc_type="article",
        pub_year=2024,
        doi=None,
        oa_status="gold",
    )
    pub = store.find_by_id(pub_id)
    assert pub is not None
    pub.license, pub.deposit_license = "cc-by", "repository-distribution"
    store.save(pub)

    relue = store.find_by_id(pub_id)
    assert relue is not None
    assert (relue.license, relue.deposit_license) == ("cc-by", "repository-distribution")
