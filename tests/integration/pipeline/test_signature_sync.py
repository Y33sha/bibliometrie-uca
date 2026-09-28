"""Synchronisation des signatures d'une notice renormalisée (`write_source_authorships`)."""

from sqlalchemy import text

from application.pipeline.normalize._authorships_batch import (
    AddressRecord,
    AuthorRecord,
    write_source_authorships,
)
from infrastructure.pipeline.normalize.authorships import PgAuthorshipsBatchQueries

_Q = PgAuthorshipsBatchQueries()


def _source_publication(conn) -> int:
    return conn.execute(
        text(
            "INSERT INTO source_publications (source, source_id, title) "
            "VALUES ('crossref', '10.9999/sync', 't') RETURNING id"
        )
    ).scalar_one()


def _write(conn, sp: int, records: list[AuthorRecord]) -> None:
    write_source_authorships(conn, _Q, "crossref", sp, records)


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
    person = conn.execute(
        text(
            "INSERT INTO persons (last_name, first_name, last_name_normalized, first_name_normalized) "
            "VALUES ('Xu', 'Zhilu', 'xu', 'zhilu') RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text("UPDATE source_authorships SET person_id = :p WHERE id = :i"),
        {"p": person, "i": sa_id},
    )
    conn.execute(
        text("INSERT INTO confirmed_authorships (source_authorship_id, person_id) VALUES (:i, :p)"),
        {"i": sa_id, "p": person},
    )
    return person


def test_auteur_ajoute_en_tete_conserve_personne_et_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    sp = _source_publication(conn)
    _write(conn, sp, [AuthorRecord(0, "Dupont, Jean"), AuthorRecord(1, "Xu, Z.")])
    xu_id = _signatures(conn, sp)[1][0]
    person = _pin(conn, xu_id)

    _write(
        conn,
        sp,
        [
            AuthorRecord(0, "Martin, Paul"),
            AuthorRecord(1, "Dupont, Jean"),
            AuthorRecord(2, "Xu, Z."),
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
    sp = _source_publication(conn)
    _write(conn, sp, [AuthorRecord(0, "Dupont, Jean"), AuthorRecord(1, "Xu, Z.")])
    before = _signatures(conn, sp)

    _write(conn, sp, [AuthorRecord(0, "Xu, Z."), AuthorRecord(1, "Dupont, Jean")])

    after = _signatures(conn, sp)
    assert after[0][0] == before[1][0]
    assert after[1][0] == before[0][0]


def test_identite_repetee_departagee_par_position(sa_sync_conn):
    conn = sa_sync_conn
    sp = _source_publication(conn)
    _write(
        conn,
        sp,
        [AuthorRecord(0, "Xu, Z."), AuthorRecord(1, "Dupont, Jean"), AuthorRecord(2, "Xu, Z.")],
    )
    before = _signatures(conn, sp)

    _write(
        conn,
        sp,
        [
            AuthorRecord(0, "Xu, Z."),
            AuthorRecord(1, "Dupont, Jean"),
            AuthorRecord(2, "Xu, Z."),
            AuthorRecord(3, "Martin, Paul"),
        ],
    )

    after = _signatures(conn, sp)
    assert [after[p][0] for p in (0, 1, 2)] == [before[p][0] for p in (0, 1, 2)]
    assert 3 in after


def test_auteur_disparu_supprime_avec_son_epinglage(sa_sync_conn):
    conn = sa_sync_conn
    sp = _source_publication(conn)
    _write(conn, sp, [AuthorRecord(0, "Dupont, Jean"), AuthorRecord(1, "Xu, Z.")])
    xu_id = _signatures(conn, sp)[1][0]
    _pin(conn, xu_id)

    _write(conn, sp, [AuthorRecord(0, "Dupont, Jean")])

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
    sp = _source_publication(conn)
    _write(conn, sp, [AuthorRecord(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")])])
    sa_id = _signatures(conn, sp)[0][0]

    _write(conn, sp, [AuthorRecord(0, "Dupont, Jean", addresses=[AddressRecord("Labo B")])])

    assert _signatures(conn, sp)[0][0] == sa_id
    assert _addresses(conn, sa_id) == ["Labo B"]


def test_signature_inchangee_laissee_en_l_etat(sa_sync_conn):
    """Une signature inchangée garde son `countries_dirty`, remis à faux par la phase affiliations."""
    conn = sa_sync_conn
    sp = _source_publication(conn)
    records = [AuthorRecord(0, "Dupont, Jean", addresses=[AddressRecord("Labo A")])]
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
