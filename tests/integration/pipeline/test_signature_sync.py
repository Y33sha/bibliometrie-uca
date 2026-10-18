"""Synchronisation des signatures d'une notice renormalisée (`sync_source_authorships`, `write_source_authorships`)."""

from functools import partial

from sqlalchemy import text

from domain.persons.signature_name import SignatureName
from domain.structures.identifiers import RorId
from pipeline.ingestion.common.fingerprint import fingerprint
from pipeline.ingestion.common.signature_queries import AuthorshipsBatchQueries
from pipeline.ingestion.common.signatures import (
    AddressRecord,
    AuthorRecord,
    SignatureSyncSettings,
    sync_source_authorships,
    write_source_authorships,
)
from tests.integration.helpers.authorships import insert_confirmed_authorship
from tests.integration.helpers.persons import insert_person
from tests.integration.helpers.publications import insert_publication
from tests.integration.helpers.sources import insert_source_publication

# Notice Crossref « 10.9999/sync », de titre « t ».
_notice = partial(insert_source_publication, source="crossref", source_id="10.9999/sync", title="t")

_Q = AuthorshipsBatchQueries()


def _rec(position: int, raw: str, **fields) -> AuthorRecord:
    return AuthorRecord(position, SignatureName(raw=raw), **fields)


def _write(conn, sp: int, records: list[AuthorRecord]) -> None:
    write_source_authorships(conn, _Q, fingerprint, "crossref", sp, records)


def _signatures(conn, sp: int) -> dict[int, tuple[int, str]]:
    """Position → (identifiant, nom brut) des signatures de la notice."""
    rows = conn.execute(
        text(
            "SELECT author_position, id, raw_author_name FROM source_authorships "
            "WHERE source_publication_id = :sp"
        ),
        {"sp": sp},
    ).all()
    return {r.author_position: (r.id, r.raw_author_name) for r in rows}


def _addresses(conn, sa_id: int) -> list[str]:
    return (
        conn.execute(
            text(
                "SELECT a.raw_text FROM source_authorship_addresses l "
                "JOIN addresses a ON a.id = l.address_id WHERE l.source_authorship_id = :i "
                "ORDER BY a.raw_text"
            ),
            {"i": sa_id},
        )
        .scalars()
        .all()
    )


def _pin(conn, sa_id: int) -> int:
    person = insert_person(conn, "Xu", first_name="Zhilu", normalizer="lower")
    conn.execute(
        text("UPDATE source_authorships SET person_id = :p WHERE id = :i"),
        {"p": person, "i": sa_id},
    )
    insert_confirmed_authorship(conn, sa_id, person_id=person)
    return person


def test_auteur_ajoute_en_tete_conserve_personne_et_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _write(conn, sp, [_rec(0, "Dupont, Jean"), _rec(1, "Xu, Z.")])
    xu_id = _signatures(conn, sp)[1][0]
    person = _pin(conn, xu_id)

    _write(
        conn,
        sp,
        [
            _rec(0, "Martin, Paul"),
            _rec(1, "Dupont, Jean"),
            _rec(2, "Xu, Z."),
        ],
    )

    assert _signatures(conn, sp)[2][0] == xu_id
    assert (
        conn.execute(
            text("SELECT person_id FROM source_authorships WHERE id = :i"), {"i": xu_id}
        ).scalar_one()
        == person
    )
    assert (
        conn.execute(
            text("SELECT person_id FROM confirmed_authorships WHERE source_authorship_id = :i"),
            {"i": xu_id},
        ).scalar_one()
        == person
    )


def test_permutation_de_positions(sa_sync_conn):
    """Deux signatures échangent leur position en une instruction (contrainte différable)."""
    conn = sa_sync_conn
    sp = _notice(conn)
    _write(conn, sp, [_rec(0, "Dupont, Jean"), _rec(1, "Xu, Z.")])
    before = _signatures(conn, sp)

    _write(conn, sp, [_rec(0, "Xu, Z."), _rec(1, "Dupont, Jean")])

    after = _signatures(conn, sp)
    assert after[0][0] == before[1][0]
    assert after[1][0] == before[0][0]


def test_identite_repetee_departagee_par_position(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _write(
        conn,
        sp,
        [_rec(0, "Xu, Z."), _rec(1, "Dupont, Jean"), _rec(2, "Xu, Z.")],
    )
    before = _signatures(conn, sp)

    _write(
        conn,
        sp,
        [
            _rec(0, "Xu, Z."),
            _rec(1, "Dupont, Jean"),
            _rec(2, "Xu, Z."),
            _rec(3, "Martin, Paul"),
        ],
    )

    after = _signatures(conn, sp)
    assert [after[p][0] for p in (0, 1, 2)] == [before[p][0] for p in (0, 1, 2)]
    assert 3 in after


def test_auteur_disparu_supprime_avec_son_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _write(conn, sp, [_rec(0, "Dupont, Jean"), _rec(1, "Xu, Z.")])
    xu_id = _signatures(conn, sp)[1][0]
    _pin(conn, xu_id)

    _write(conn, sp, [_rec(0, "Dupont, Jean")])

    assert set(_signatures(conn, sp)) == {0}
    assert (
        conn.execute(
            text("SELECT count(*) FROM confirmed_authorships WHERE source_authorship_id = :i"),
            {"i": xu_id},
        ).scalar_one()
        == 0
    )


def test_adresses_reecrites_si_modifiees(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _write(conn, sp, [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")])])
    sa_id = _signatures(conn, sp)[0][0]

    _write(conn, sp, [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo B")])])

    assert _signatures(conn, sp)[0][0] == sa_id
    assert _addresses(conn, sa_id) == ["Labo B"]


def _authorships_dirty(conn, publication_id: int) -> bool:
    return conn.execute(
        text("SELECT authorships_dirty FROM publications WHERE id = :p"), {"p": publication_id}
    ).scalar_one()


def test_regroupement_demande_par_les_seuls_changements_d_identite_position_ou_roles(sa_sync_conn):
    conn = sa_sync_conn
    publication = insert_publication(conn)
    sp = _notice(conn, publication)
    _write(
        conn, sp, [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")]), _rec(1, "Xu, Z.")]
    )
    conn.execute(text("UPDATE publications SET authorships_dirty = false"))

    _write(
        conn, sp, [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo B")]), _rec(1, "Xu, Z.")]
    )
    assert not _authorships_dirty(conn, publication)

    _write(
        conn, sp, [_rec(0, "Xu, Z."), _rec(1, "Dupont, Jean", addresses=[AddressRecord("Labo B")])]
    )
    assert _authorships_dirty(conn, publication)

    conn.execute(text("UPDATE publications SET authorships_dirty = false"))
    _write(
        conn,
        sp,
        [
            _rec(0, "Xu, Z."),
            _rec(
                1, "Dupont, Jean", roles=["author", "editor"], addresses=[AddressRecord("Labo B")]
            ),
        ],
    )
    assert _authorships_dirty(conn, publication)

    conn.execute(text("UPDATE publications SET authorships_dirty = false"))
    _write(
        conn,
        sp,
        [
            _rec(0, "Xu, Zhilu"),
            _rec(
                1, "Dupont, Jean", roles=["author", "editor"], addresses=[AddressRecord("Labo B")]
            ),
        ],
    )
    assert _authorships_dirty(conn, publication)


def test_decomptes_des_auteurs_de_la_notice(sa_sync_conn):
    """Seules les signatures au rôle author, non collectives, comptent ; un nom répété compte une fois parmi les noms distincts."""
    conn = sa_sync_conn
    sp = _notice(conn)
    author = ["author"]
    _write(
        conn,
        sp,
        [
            _rec(0, "Dupont, Jean", roles=author),
            _rec(1, "ATLAS Collaboration", roles=author),
            _rec(2, "Dupont, Jean", roles=author),
            AuthorRecord(None, SignatureName(raw="Martin, Paul"), roles=["jury_member"]),
        ],
    )

    counts = conn.execute(
        text("SELECT author_count, distinct_author_count FROM source_publications WHERE id = :sp"),
        {"sp": sp},
    ).one()
    assert tuple(counts) == (2, 1)


def test_marque_collective_ecrite_et_reecrite(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _write(conn, sp, [_rec(0, "Big Lab"), _rec(1, "ATLAS Collaboration")])
    _write(conn, sp, [_rec(0, "Big Lab", collective=True), _rec(1, "ATLAS Collaboration")])

    rows = conn.execute(
        text(
            "SELECT author_position, collective FROM source_authorships "
            "WHERE source_publication_id = :sp ORDER BY author_position"
        ),
        {"sp": sp},
    ).all()
    assert [tuple(r) for r in rows] == [(0, True), (1, True)]


def test_signature_devenue_collective_reinseree_sans_personne(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _write(conn, sp, [_rec(0, "Big Lab")])
    old_id = _signatures(conn, sp)[0][0]
    _pin(conn, old_id)

    _write(conn, sp, [_rec(0, "Big Lab", collective=True)])

    new_id = _signatures(conn, sp)[0][0]
    assert new_id != old_id
    assert (
        conn.execute(
            text("SELECT person_id FROM source_authorships WHERE id = :i"), {"i": new_id}
        ).scalar_one()
        is None
    )


def _rors(conn, sa_id: int) -> list[str]:
    return (
        conn.execute(
            text(
                "SELECT ror_id FROM source_authorship_rors WHERE source_authorship_id = :i "
                "ORDER BY ror_id"
            ),
            {"i": sa_id},
        )
        .scalars()
        .all()
    )


def test_ror_ecrits_a_l_insertion_et_reecrits_si_modifies(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    univ, labo = RorId("01a8ajp46"), RorId("03vgfxd91")
    _write(conn, sp, [_rec(0, "Dupont, Jean", ror_ids=frozenset({univ, labo}))])
    sa_id = _signatures(conn, sp)[0][0]
    assert _rors(conn, sa_id) == ["01a8ajp46", "03vgfxd91"]

    _write(conn, sp, [_rec(0, "Dupont, Jean", ror_ids=frozenset({labo}))])

    assert _signatures(conn, sp)[0][0] == sa_id
    assert _rors(conn, sa_id) == ["03vgfxd91"]


def _hal_structures(conn, sa_id: int) -> list[int]:
    return (
        conn.execute(
            text(
                "SELECT hal_structure_id FROM source_authorship_hal_structures"
                " WHERE source_authorship_id = :i ORDER BY hal_structure_id"
            ),
            {"i": sa_id},
        )
        .scalars()
        .all()
    )


def test_structures_hal_ecrites_a_l_insertion_et_reecrites_si_modifiees(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _write(conn, sp, [_rec(0, "Dupont, Jean", hal_structure_ids=frozenset({483019, 1063727}))])
    sa_id = _signatures(conn, sp)[0][0]
    assert _hal_structures(conn, sa_id) == [483019, 1063727]

    _write(conn, sp, [_rec(0, "Dupont, Jean", hal_structure_ids=frozenset({1063727}))])

    assert _signatures(conn, sp)[0][0] == sa_id
    assert _hal_structures(conn, sa_id) == [1063727]


def test_ror_rattaches_a_l_adresse_de_leur_affiliation(sa_sync_conn):
    """Un ROR d'affiliation pointe sur son adresse ; un ROR sans texte d'affiliation sur la seule signature."""
    conn = sa_sync_conn
    sp = _notice(conn)
    univ, labo = RorId("01a8ajp46"), RorId("03vgfxd91")
    _write(
        conn,
        sp,
        [
            _rec(
                0,
                "Dupont, Jean",
                addresses=[AddressRecord("Labo A", ror_ids=frozenset({labo}))],
                ror_ids=frozenset({univ}),
            )
        ],
    )
    sa_id = _signatures(conn, sp)[0][0]

    rows = conn.execute(
        text("""
            SELECT r.ror_id, a.raw_text
            FROM source_authorship_rors r
            LEFT JOIN addresses a ON a.id = r.address_id
            WHERE r.source_authorship_id = :i
            ORDER BY r.ror_id
        """),
        {"i": sa_id},
    ).all()
    assert [tuple(r) for r in rows] == [("01a8ajp46", None), ("03vgfxd91", "Labo A")]


def test_signature_inchangee_laissee_en_l_etat(sa_sync_conn):
    """Une signature inchangée garde son `countries_dirty`, remis à faux par la phase affiliations."""
    conn = sa_sync_conn
    sp = _notice(conn)
    records = [_rec(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")])]
    _write(conn, sp, records)
    sa_id = _signatures(conn, sp)[0][0]
    conn.execute(
        text("UPDATE source_authorships SET countries_dirty = false WHERE id = :i"), {"i": sa_id}
    )

    _write(conn, sp, records)

    assert (
        conn.execute(
            text("SELECT countries_dirty FROM source_authorships WHERE id = :i"), {"i": sa_id}
        ).scalar_one()
        is False
    )
    assert _addresses(conn, sa_id) == ["Labo A"]


def _build(block) -> list[AuthorRecord]:
    return [_rec(i, name) for i, name in enumerate(block["names"])]


def _build_upper(block) -> list[AuthorRecord]:
    """Construction selon une règle de normalisation modifiée : noms en majuscules."""
    return [_rec(i, name.upper()) for i, name in enumerate(block["names"])]


def _sync(conn, sp: int, names: list[str], build=_build, *, normalize_full: bool = False) -> None:
    settings = SignatureSyncSettings(fingerprint=fingerprint, normalize_full=normalize_full)
    sync_source_authorships(conn, _Q, settings, "crossref", sp, {"names": names}, build)


def test_bloc_inchange_laisse_les_signatures_en_l_etat(sa_sync_conn):
    """Une règle modifiée reste sans effet tant que le bloc auteurs est inchangé."""
    conn = sa_sync_conn
    sp = _notice(conn)
    _sync(conn, sp, ["Dupont, Jean"])

    _sync(conn, sp, ["Dupont, Jean"], _build_upper)

    assert _signatures(conn, sp)[0][1] == "Dupont, Jean"


def test_normalize_full_applique_une_regle_modifiee(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _sync(conn, sp, ["Dupont, Jean"])
    sa_id = _signatures(conn, sp)[0][0]

    _sync(conn, sp, ["Dupont, Jean"], _build_upper, normalize_full=True)

    assert _signatures(conn, sp)[0] == (sa_id, "DUPONT, JEAN")


def test_bloc_modifie_synchronise_et_enregistre_son_empreinte(sa_sync_conn):
    conn = sa_sync_conn
    sp = _notice(conn)
    _sync(conn, sp, ["Dupont, Jean"])

    _sync(conn, sp, ["Dupont, Jean", "Martin, Paul"])

    assert [name for _, name in sorted(_signatures(conn, sp).values())] == [
        "Dupont, Jean",
        "Martin, Paul",
    ]
    assert _Q.fetch_authors_hash(conn, sp) == fingerprint(
        {"names": ["Dupont, Jean", "Martin, Paul"]}
    )


def test_signature_sans_position_garde_sa_confirmation(sa_sync_conn):
    """Thèse renormalisée avec un rapporteur de plus : le directeur, sans position d'auteur, garde son identifiant et sa confirmation ; les signatures insérées reçoivent leurs adresses."""
    conn = sa_sync_conn
    sp = insert_source_publication(conn, source="theses", source_id="s123", title="t")
    lab = [AddressRecord(text="LIMOS")]

    def thesis(*extra: AuthorRecord) -> list[AuthorRecord]:
        return [
            _rec(0, "Dupont, Marie", roles=["author"], addresses=lab),
            AuthorRecord(
                None, SignatureName(raw="Xu, Z."), roles=["thesis_director"], addresses=lab
            ),
            *extra,
        ]

    write_source_authorships(conn, _Q, fingerprint, "theses", sp, thesis())
    director_id = _signatures(conn, sp)[None][0]
    person = _pin(conn, director_id)

    reviewer = AuthorRecord(
        None, SignatureName(raw="Durand, Paul"), roles=["reviewer"], addresses=lab
    )
    write_source_authorships(conn, _Q, fingerprint, "theses", sp, thesis(reviewer))

    rows = conn.execute(
        text(
            "SELECT id, raw_author_name FROM source_authorships "
            "WHERE source_publication_id = :sp AND author_position IS NULL ORDER BY id"
        ),
        {"sp": sp},
    ).all()
    assert [r.id for r in rows][0] == director_id
    assert (
        conn.execute(
            text("SELECT person_id FROM confirmed_authorships WHERE source_authorship_id = :i"),
            {"i": director_id},
        ).scalar()
        == person
    )
    reviewer_id = next(r.id for r in rows if r.raw_author_name == "Durand, Paul")
    assert _addresses(conn, reviewer_id) == ["LIMOS"]
