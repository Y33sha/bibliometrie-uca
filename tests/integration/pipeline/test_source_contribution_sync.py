"""Synchronisation des contributions sources d'un enregistrement source renormalisé (`sync_source_contributions`, `write_source_contributions`)."""

from functools import partial

from sqlalchemy import text

from domain.persons.contributor_name import ContributorName
from domain.structures.identifiers import RorId
from infrastructure.db.queues import Queue
from pipeline.ingestion.common.fingerprint import fingerprint
from pipeline.ingestion.common.source_contribution_store import (
    SourceContributionStore,
    mark_source_contributions_to_resync,
)
from pipeline.ingestion.common.source_contributions import (
    AddressRecord,
    AuthorRecord,
    sync_source_contributions,
    write_source_contributions,
)
from tests.integration.helpers.alignment import align_source_contributions
from tests.integration.helpers.contributions import insert_confirmed_source_contribution
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.queues import clear, queued
from tests.integration.helpers.sources import insert_source_record

# Enregistrement source Crossref « 10.9999/sync », de titre « t ».
_source_record = partial(
    insert_source_record, source="crossref", source_id="10.9999/sync", title="t"
)


def _rec(position: int, raw: str, **fields) -> AuthorRecord:
    return AuthorRecord(position, ContributorName(raw=raw), **fields)


def _write(conn, source_record: int, records: list[AuthorRecord]) -> None:
    write_source_contributions(SourceContributionStore(conn), "crossref", source_record, records)


def _source_contributions(conn, source_record: int) -> dict[int, tuple[int, str]]:
    """Renvoie position → (identifiant, nom brut) des contributions sources de l'enregistrement source."""
    rows = conn.execute(
        text(
            "SELECT author_position, id, raw_author_name FROM source_contributions "
            "WHERE source_record_id = :sp"
        ),
        {"sp": source_record},
    ).all()
    return {r.author_position: (r.id, r.raw_author_name) for r in rows}


def _addresses(conn, source_contribution_id: int) -> list[str]:
    return (
        conn.execute(
            text(
                "SELECT a.raw_text FROM source_contribution_addresses l "
                "JOIN addresses a ON a.id = l.address_id WHERE l.source_contribution_id = :i "
                "ORDER BY a.raw_text"
            ),
            {"i": source_contribution_id},
        )
        .scalars()
        .all()
    )


def _pin(conn, source_contribution_id: int) -> int:
    person = insert_person(conn, "Xu", first_name="Zhilu", normalizer="lower")
    insert_confirmed_source_contribution(conn, source_contribution_id, person_id=person)
    return person


def test_auteur_ajoute_en_tete_conserve_l_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _write(conn, source_record, [_rec(0, "Dupont, Jean"), _rec(1, "Xu, Z.")])
    xu_id = _source_contributions(conn, source_record)[1][0]
    person = _pin(conn, xu_id)

    _write(
        conn,
        source_record,
        [
            _rec(0, "Martin, Paul"),
            _rec(1, "Dupont, Jean"),
            _rec(2, "Xu, Z."),
        ],
    )

    assert _source_contributions(conn, source_record)[2][0] == xu_id
    assert (
        conn.execute(
            text(
                "SELECT person_id FROM confirmed_source_contributions WHERE source_contribution_id = :i"
            ),
            {"i": xu_id},
        ).scalar_one()
        == person
    )


def test_permutation_de_positions(sa_sync_conn):
    """Deux contributions sources échangent leur position en une instruction (contrainte différable)."""
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _write(conn, source_record, [_rec(0, "Dupont, Jean"), _rec(1, "Xu, Z.")])
    before = _source_contributions(conn, source_record)

    _write(conn, source_record, [_rec(0, "Xu, Z."), _rec(1, "Dupont, Jean")])

    after = _source_contributions(conn, source_record)
    assert after[0][0] == before[1][0]
    assert after[1][0] == before[0][0]


def test_identite_repetee_departagee_par_position(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _write(
        conn,
        source_record,
        [_rec(0, "Xu, Z."), _rec(1, "Dupont, Jean"), _rec(2, "Xu, Z.")],
    )
    before = _source_contributions(conn, source_record)

    _write(
        conn,
        source_record,
        [
            _rec(0, "Xu, Z."),
            _rec(1, "Dupont, Jean"),
            _rec(2, "Xu, Z."),
            _rec(3, "Martin, Paul"),
        ],
    )

    after = _source_contributions(conn, source_record)
    assert [after[p][0] for p in (0, 1, 2)] == [before[p][0] for p in (0, 1, 2)]
    assert 3 in after


def test_auteur_disparu_supprime_avec_son_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _write(conn, source_record, [_rec(0, "Dupont, Jean"), _rec(1, "Xu, Z.")])
    xu_id = _source_contributions(conn, source_record)[1][0]
    _pin(conn, xu_id)

    _write(conn, source_record, [_rec(0, "Dupont, Jean")])

    assert set(_source_contributions(conn, source_record)) == {0}
    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM confirmed_source_contributions WHERE source_contribution_id = :i"
            ),
            {"i": xu_id},
        ).scalar_one()
        == 0
    )


def test_adresses_reecrites_si_modifiees(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _write(conn, source_record, [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")])])
    source_contribution_id = _source_contributions(conn, source_record)[0][0]

    _write(conn, source_record, [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo B")])])

    assert _source_contributions(conn, source_record)[0][0] == source_contribution_id
    assert _addresses(conn, source_contribution_id) == ["Labo B"]


def _marked_for_grouping(conn, publication_id: int) -> bool:
    return publication_id in queued(conn, Queue.PUBLICATION_CONTRIBUTIONS)


def test_realignement_demande_par_les_seuls_changements_d_identite_position_ou_roles(sa_sync_conn):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    source_record = _source_record(conn, publication)
    _write(
        conn,
        source_record,
        [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")]), _rec(1, "Xu, Z.")],
    )
    clear(conn, Queue.PUBLICATION_CONTRIBUTIONS)

    _write(
        conn,
        source_record,
        [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo B")]), _rec(1, "Xu, Z.")],
    )
    assert not _marked_for_grouping(conn, publication)

    _write(
        conn,
        source_record,
        [_rec(0, "Xu, Z."), _rec(1, "Dupont, Jean", addresses=[AddressRecord("Labo B")])],
    )
    assert _marked_for_grouping(conn, publication)

    clear(conn, Queue.PUBLICATION_CONTRIBUTIONS)
    _write(
        conn,
        source_record,
        [
            _rec(0, "Xu, Z."),
            _rec(
                1, "Dupont, Jean", roles=["author", "editor"], addresses=[AddressRecord("Labo B")]
            ),
        ],
    )
    assert _marked_for_grouping(conn, publication)

    clear(conn, Queue.PUBLICATION_CONTRIBUTIONS)
    _write(
        conn,
        source_record,
        [
            _rec(0, "Xu, Zhilu"),
            _rec(
                1, "Dupont, Jean", roles=["author", "editor"], addresses=[AddressRecord("Labo B")]
            ),
        ],
    )
    assert _marked_for_grouping(conn, publication)


def test_les_contributions_des_contributions_sources_dont_les_roles_changent_sont_marquees(
    sa_sync_conn,
):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    source_record = _source_record(conn, publication)
    _write(conn, source_record, [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")])])
    source_contribution_id = _source_contributions(conn, source_record)[0][0]
    contribution = align_source_contributions(
        conn, publication, [(source_contribution_id, source_record)]
    )
    clear(conn, Queue.CONTRIBUTION_ATTRIBUTES)

    _write(conn, source_record, [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo B")])])
    assert queued(conn, Queue.CONTRIBUTION_ATTRIBUTES) == set()

    _write(
        conn,
        source_record,
        [_rec(0, "Dupont, Jean", roles=["author", "editor"], addresses=[AddressRecord("Labo B")])],
    )
    assert queued(conn, Queue.CONTRIBUTION_ATTRIBUTES) == {contribution}


def test_decomptes_des_auteurs_de_l_enregistrement_source(sa_sync_conn):
    """Seules les contributions sources au rôle author, non collectives, comptent ; un nom répété compte une fois parmi les noms distincts."""
    conn = sa_sync_conn
    source_record = _source_record(conn)
    author = ["author"]
    _write(
        conn,
        source_record,
        [
            _rec(0, "Dupont, Jean", roles=author),
            _rec(1, "ATLAS Collaboration", roles=author),
            _rec(2, "Dupont, Jean", roles=author),
            AuthorRecord(None, ContributorName(raw="Martin, Paul"), roles=["jury_member"]),
        ],
    )

    counts = conn.execute(
        text("SELECT author_count, distinct_author_count FROM source_records WHERE id = :sp"),
        {"sp": source_record},
    ).one()
    assert tuple(counts) == (2, 1)


def test_marque_collective_ecrite_et_reecrite(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _write(conn, source_record, [_rec(0, "Big Lab"), _rec(1, "ATLAS Collaboration")])
    _write(
        conn, source_record, [_rec(0, "Big Lab", collective=True), _rec(1, "ATLAS Collaboration")]
    )

    rows = conn.execute(
        text(
            "SELECT author_position, collective FROM source_contributions "
            "WHERE source_record_id = :sp ORDER BY author_position"
        ),
        {"sp": source_record},
    ).all()
    assert [tuple(r) for r in rows] == [(0, True), (1, True)]


def test_contribution_source_devenue_collective_reinseree_sans_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _write(conn, source_record, [_rec(0, "Big Lab")])
    old_id = _source_contributions(conn, source_record)[0][0]
    _pin(conn, old_id)

    _write(conn, source_record, [_rec(0, "Big Lab", collective=True)])

    new_id = _source_contributions(conn, source_record)[0][0]
    assert new_id != old_id
    assert (
        conn.execute(
            text(
                "SELECT person_id FROM confirmed_source_contributions WHERE source_contribution_id = :i"
            ),
            {"i": new_id},
        ).scalar_one_or_none()
        is None
    )


def _rors(conn, source_contribution_id: int) -> list[str]:
    return (
        conn.execute(
            text(
                "SELECT ror_id FROM source_contribution_rors WHERE source_contribution_id = :i "
                "ORDER BY ror_id"
            ),
            {"i": source_contribution_id},
        )
        .scalars()
        .all()
    )


def test_ror_ecrits_a_l_insertion_et_reecrits_si_modifies(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    univ, labo = RorId("01a8ajp46"), RorId("03vgfxd91")
    _write(conn, source_record, [_rec(0, "Dupont, Jean", ror_ids=frozenset({univ, labo}))])
    source_contribution_id = _source_contributions(conn, source_record)[0][0]
    assert _rors(conn, source_contribution_id) == ["01a8ajp46", "03vgfxd91"]

    _write(conn, source_record, [_rec(0, "Dupont, Jean", ror_ids=frozenset({labo}))])

    assert _source_contributions(conn, source_record)[0][0] == source_contribution_id
    assert _rors(conn, source_contribution_id) == ["03vgfxd91"]


def _hal_structures(conn, source_contribution_id: int) -> list[int]:
    return (
        conn.execute(
            text(
                "SELECT hal_structure_id FROM source_contribution_hal_structures"
                " WHERE source_contribution_id = :i ORDER BY hal_structure_id"
            ),
            {"i": source_contribution_id},
        )
        .scalars()
        .all()
    )


def test_structures_hal_ecrites_a_l_insertion_et_reecrites_si_modifiees(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _write(
        conn,
        source_record,
        [_rec(0, "Dupont, Jean", hal_structure_ids=frozenset({483019, 1063727}))],
    )
    source_contribution_id = _source_contributions(conn, source_record)[0][0]
    assert _hal_structures(conn, source_contribution_id) == [483019, 1063727]

    _write(conn, source_record, [_rec(0, "Dupont, Jean", hal_structure_ids=frozenset({1063727}))])

    assert _source_contributions(conn, source_record)[0][0] == source_contribution_id
    assert _hal_structures(conn, source_contribution_id) == [1063727]


def test_ror_rattaches_a_l_adresse_de_leur_affiliation(sa_sync_conn):
    """Un ROR d'affiliation pointe sur son adresse ; un ROR sans texte d'affiliation sur la seule contribution source."""
    conn = sa_sync_conn
    source_record = _source_record(conn)
    univ, labo = RorId("01a8ajp46"), RorId("03vgfxd91")
    _write(
        conn,
        source_record,
        [
            _rec(
                0,
                "Dupont, Jean",
                addresses=[AddressRecord("Labo A", ror_ids=frozenset({labo}))],
                ror_ids=frozenset({univ}),
            )
        ],
    )
    source_contribution_id = _source_contributions(conn, source_record)[0][0]

    rows = conn.execute(
        text("""
            SELECT r.ror_id, a.raw_text
            FROM source_contribution_rors r
            LEFT JOIN addresses a ON a.id = r.address_id
            WHERE r.source_contribution_id = :i
            ORDER BY r.ror_id
        """),
        {"i": source_contribution_id},
    ).all()
    assert [tuple(r) for r in rows] == [("01a8ajp46", None), ("03vgfxd91", "Labo A")]


def test_contribution_source_inchangee_laissee_en_l_etat(sa_sync_conn):
    """Une contribution source inchangée reste hors de la file du recalcul des pays."""
    conn = sa_sync_conn
    source_record = _source_record(conn)
    records = [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")])]
    _write(conn, source_record, records)
    source_contribution_id = _source_contributions(conn, source_record)[0][0]
    assert queued(conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES) == {source_contribution_id}
    clear(conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES)

    _write(conn, source_record, records)

    assert queued(conn, Queue.SOURCE_CONTRIBUTION_COUNTRIES) == set()
    assert _addresses(conn, source_contribution_id) == ["Labo A"]


def _build(block) -> list[AuthorRecord]:
    return [_rec(i, name) for i, name in enumerate(block["names"])]


def _build_upper(block) -> list[AuthorRecord]:
    """Construit les auteurs selon une règle de normalisation modifiée : noms en majuscules."""
    return [_rec(i, name.upper()) for i, name in enumerate(block["names"])]


def _sync(conn, source_record: int, names: list[str], build=_build) -> None:
    sync_source_contributions(
        SourceContributionStore(conn), "crossref", source_record, {"names": names}, build
    )


def test_bloc_inchange_laisse_les_contributions_sources_en_l_etat(sa_sync_conn):
    """Une règle modifiée reste sans effet tant que le bloc auteurs est inchangé."""
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _sync(conn, source_record, ["Dupont, Jean"])

    _sync(conn, source_record, ["Dupont, Jean"], _build_upper)

    assert _source_contributions(conn, source_record)[0][1] == "Dupont, Jean"


def test_enregistrement_source_marque_applique_une_regle_modifiee(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _sync(conn, source_record, ["Dupont, Jean"])
    source_contribution_id = _source_contributions(conn, source_record)[0][0]

    assert mark_source_contributions_to_resync(conn, "crossref") == 1
    _sync(conn, source_record, ["Dupont, Jean"], _build_upper)

    assert _source_contributions(conn, source_record)[0] == (source_contribution_id, "DUPONT, JEAN")


def test_bloc_modifie_synchronise_et_enregistre_son_empreinte(sa_sync_conn):
    conn = sa_sync_conn
    source_record = _source_record(conn)
    _sync(conn, source_record, ["Dupont, Jean"])

    _sync(conn, source_record, ["Dupont, Jean", "Martin, Paul"])

    assert [name for _, name in sorted(_source_contributions(conn, source_record).values())] == [
        "Dupont, Jean",
        "Martin, Paul",
    ]
    assert SourceContributionStore(conn).fetch_authors_hash(source_record) == fingerprint(
        {"names": ["Dupont, Jean", "Martin, Paul"]}
    )


def test_contribution_source_sans_position_garde_sa_confirmation(sa_sync_conn):
    """Thèse renormalisée avec un rapporteur de plus : le directeur, sans position d'auteur, garde son identifiant et sa confirmation ; les contributions sources insérées reçoivent leurs adresses."""
    conn = sa_sync_conn
    source_record = insert_source_record(conn, source="theses", source_id="s123", title="t")
    lab = [AddressRecord(text="LIMOS")]

    def thesis(*extra: AuthorRecord) -> list[AuthorRecord]:
        return [
            _rec(0, "Dupont, Marie", roles=["author"], addresses=lab),
            AuthorRecord(
                None, ContributorName(raw="Xu, Z."), roles=["thesis_director"], addresses=lab
            ),
            *extra,
        ]

    write_source_contributions(SourceContributionStore(conn), "theses", source_record, thesis())
    director_id = _source_contributions(conn, source_record)[None][0]
    person = _pin(conn, director_id)

    reviewer = AuthorRecord(
        None, ContributorName(raw="Durand, Paul"), roles=["reviewer"], addresses=lab
    )
    write_source_contributions(
        SourceContributionStore(conn), "theses", source_record, thesis(reviewer)
    )

    rows = conn.execute(
        text(
            "SELECT id, raw_author_name FROM source_contributions "
            "WHERE source_record_id = :sp AND author_position IS NULL ORDER BY id"
        ),
        {"sp": source_record},
    ).all()
    assert [r.id for r in rows][0] == director_id
    assert (
        conn.execute(
            text(
                "SELECT person_id FROM confirmed_source_contributions WHERE source_contribution_id = :i"
            ),
            {"i": director_id},
        ).scalar()
        == person
    )
    reviewer_id = next(r.id for r in rows if r.raw_author_name == "Durand, Paul")
    assert _addresses(conn, reviewer_id) == ["LIMOS"]
