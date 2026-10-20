from sqlalchemy import text

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, RorStatus, RorType
from pipeline.transformation.structures.ror import RorDumpQueries
from tests.integration.helpers.addresses import ensure_country, insert_address
from tests.integration.helpers.sources import insert_signature, insert_source_record

UNIV, LABO = RorId("01a8ajp46"), RorId("03vgfxd91")


def _org(ror_id, country_code="fr"):
    return RorOrganization(
        ror_id=ror_id,
        name=f"Organisation {ror_id}",
        country_code=country_code,
        types=frozenset({RorType.EDUCATION, RorType.FACILITY}),
        status=RorStatus.ACTIVE,
        parent_ids=frozenset(),
        child_ids=frozenset(),
    )


def test_replace_all_vide_puis_remplit_les_tables(sa_sync_conn):
    repo = RorDumpQueries(sa_sync_conn)
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
    repo = RorDumpQueries(sa_sync_conn)
    repo.replace_all([_org(UNIV)], [], version="v2.14")
    repo.replace_all([_org(UNIV)], [], version="v2.14")
    assert repo.last_imported_version() == "v2.14"


def test_un_changement_de_pays_marque_les_signatures_et_les_adresses_qui_citent_l_organisation(
    sa_sync_conn,
):
    repo = RorDumpQueries(sa_sync_conn)
    repo.replace_all([_org(UNIV), _org(LABO)], [], version="v2.13")
    record = insert_source_record(sa_sync_conn, source="openalex", source_id="W1")
    without_address = insert_signature(sa_sync_conn, record, source="openalex")
    with_address = insert_signature(sa_sync_conn, record, source="openalex", author_position=1)
    unchanged = insert_signature(sa_sync_conn, record, source="openalex", author_position=2)
    address = insert_address(sa_sync_conn, "Institut, Paris")
    ensure_country(sa_sync_conn, "fr")
    sa_sync_conn.execute(
        text(
            "INSERT INTO source_contribution_rors (source_contribution_id, ror_id, address_id)"
            " VALUES (:a, :univ, NULL), (:b, :univ, :addr), (:c, :labo, NULL)"
        ),
        {
            "a": without_address,
            "b": with_address,
            "c": unchanged,
            "univ": UNIV.value,
            "labo": LABO.value,
            "addr": address,
        },
    )
    sa_sync_conn.execute(
        text(
            "INSERT INTO address_country_candidates (address_id, country_code, method)"
            " VALUES (:addr, 'fr', 'ror'), (:addr, 'fr', 'city')"
        ),
        {"addr": address},
    )
    sa_sync_conn.execute(text("UPDATE source_contributions SET countries_dirty = false"))
    sa_sync_conn.execute(text("UPDATE addresses SET candidates_dirty = false"))

    repo.replace_all([_org(UNIV, "it"), _org(LABO)], [], version="v2.14")

    dirty = set(
        sa_sync_conn.execute(
            text("SELECT id FROM source_contributions WHERE countries_dirty")
        ).scalars()
    )
    assert dirty == {without_address}
    methods = (
        sa_sync_conn.execute(
            text("SELECT method::text FROM address_country_candidates WHERE address_id = :a"),
            {"a": address},
        )
        .scalars()
        .all()
    )
    assert methods == ["city"]
    assert sa_sync_conn.execute(
        text("SELECT candidates_dirty FROM addresses WHERE id = :a"), {"a": address}
    ).scalar_one()
