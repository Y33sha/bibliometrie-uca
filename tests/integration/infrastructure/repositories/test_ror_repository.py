from sqlalchemy import text

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, RorStatus, RorType
from infrastructure.repositories import ror_repository

UNIV, LABO = RorId("01a8ajp46"), RorId("03vgfxd91")


def _org(ror_id):
    return RorOrganization(
        ror_id=ror_id,
        name=f"Organisation {ror_id}",
        country_code="fr",
        types=frozenset({RorType.EDUCATION, RorType.FACILITY}),
        status=RorStatus.ACTIVE,
        parent_ids=frozenset(),
        child_ids=frozenset(),
    )


def test_replace_all_vide_puis_remplit_les_tables(sa_sync_conn):
    repo = ror_repository(sa_sync_conn)
    repo.replace_all([_org(RorId("02feahw73"))], [], version="v2.13")
    repo.replace_all([_org(UNIV), _org(LABO)], [(UNIV, LABO)], version="v2.14")

    rows = sa_sync_conn.execute(
        text("SELECT ror_id, country_code, types::text[] FROM ror_organizations ORDER BY ror_id")
    ).all()
    assert [tuple(r) for r in rows] == [
        ("01a8ajp46", "fr", ["education", "facility"]),
        ("03vgfxd91", "fr", ["education", "facility"]),
    ]
    relations = sa_sync_conn.execute(
        text("SELECT parent_ror_id, child_ror_id FROM ror_relations")
    ).all()
    assert [tuple(r) for r in relations] == [("01a8ajp46", "03vgfxd91")]
    assert repo.last_imported_version() == "v2.14"


def test_reimport_d_une_version_deja_importee(sa_sync_conn):
    repo = ror_repository(sa_sync_conn)
    repo.replace_all([_org(UNIV)], [], version="v2.14")
    repo.replace_all([_org(UNIV)], [], version="v2.14")
    assert repo.last_imported_version() == "v2.14"
