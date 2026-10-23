from sqlalchemy import text

from domain.structures.identifiers import RorId
from domain.structures.ror import RorOrganization, RorStatus, RorType
from infrastructure.db.queues import Queue
from pipeline.transformation.structures.ror import RorStore
from tests.integration.helpers.addresses import ensure_country, insert_address
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_contribution, insert_source_record

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
    store = RorStore(sa_sync_conn)
    store.replace_all([_org(RorId("02feahw73"))], [], version="v2.13")
    store.replace_all([_org(UNIV), _org(LABO)], [(UNIV, LABO)], version="v2.14")

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
    assert store.last_imported_version() == "v2.14"


def test_reimport_d_une_version_deja_importee(sa_sync_conn):
    store = RorStore(sa_sync_conn)
    store.replace_all([_org(UNIV)], [], version="v2.14")
    store.replace_all([_org(UNIV)], [], version="v2.14")
    assert store.last_imported_version() == "v2.14"


def test_un_changement_de_pays_marque_les_contributions_sources_et_les_adresses_qui_citent_l_organisation(
    sa_sync_conn,
):
    store = RorStore(sa_sync_conn)
    store.replace_all([_org(UNIV), _org(LABO)], [], version="v2.13")
    record = insert_source_record(sa_sync_conn, source="openalex", source_id="W1")
    without_address = insert_source_contribution(sa_sync_conn, record, source="openalex")
    with_address = insert_source_contribution(
        sa_sync_conn, record, source="openalex", author_position=1
    )
    unchanged = insert_source_contribution(
        sa_sync_conn, record, source="openalex", author_position=2
    )
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
    clear(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES)
    clear(sa_sync_conn, Queue.ADDRESS_CANDIDATES)

    store.replace_all([_org(UNIV, "it"), _org(LABO)], [], version="v2.14")

    assert queued(sa_sync_conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES) == {without_address}
    methods = (
        sa_sync_conn.execute(
            text("SELECT method::text FROM address_country_candidates WHERE address_id = :a"),
            {"a": address},
        )
        .scalars()
        .all()
    )
    assert methods == ["city"]
    assert queued(sa_sync_conn, Queue.ADDRESS_CANDIDATES) == {address}
