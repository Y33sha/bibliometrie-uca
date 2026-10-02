"""Écriture des frais de publication : périmètre de la base, idempotence, rattachements."""

from sqlalchemy import text

from infrastructure.repositories import publication_repository
from interfaces.cli.imports.import_apc import import_payments


def _payment(
    doi: str | None,
    *,
    institution: str = "CNRS",
    amount: float = 500.0,
    open_access_fee: bool = True,
) -> dict:
    return {
        "doi": doi,
        "amount_eur_ht": amount,
        "billing_year": 2022,
        "pub_year": 2022,
        "publisher_name": None,
        "journal_name": None,
        "issn": None,
        "institution": institution,
        "budget": None,
        "coman_id": None,
        "lab_name": None,
        "remarks": None,
        "open_access_fee": open_access_fee,
    }


def _publication(conn, doi: str) -> int:
    return publication_repository(conn).create(
        title="t",
        title_normalized="t",
        doc_type="article",
        pub_year=2022,
        doi=doi,
        oa_status="unknown",
    )


def _count(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM apc_payments")).scalar_one()


def test_seuls_les_doi_de_la_base_sont_importes(sa_sync_conn):
    pub = _publication(sa_sync_conn, "10.9/apc-a")

    stats = import_payments(
        sa_sync_conn, [_payment("10.9/apc-a"), _payment("10.9/hors-base"), _payment(None)], "f.csv"
    )

    assert (stats.read, stats.in_base, stats.inserted) == (3, 1, 1)
    assert (
        sa_sync_conn.execute(
            text("SELECT publication_id FROM apc_payments WHERE doi = '10.9/apc-a'")
        ).scalar_one()
        == pub
    )


def test_reimport_sans_doublon(sa_sync_conn):
    """Même DOI, même payeur, même montant, même type de frais : une seule ligne, quel que soit le nombre d'imports."""
    _publication(sa_sync_conn, "10.9/apc-b")
    payments = [_payment("10.9/apc-b"), _payment("10.9/apc-b")]

    first = import_payments(sa_sync_conn, payments, "f.csv")
    second = import_payments(sa_sync_conn, payments, "f.csv")

    assert (first.inserted, second.inserted) == (1, 0)
    assert _count(sa_sync_conn) == 1


def test_laboratoire_et_payeur_rattaches_par_les_formes_de_noms(sa_sync_conn):
    """Le payeur sert de contexte à une forme de laboratoire valable seulement en présence de son établissement."""
    _publication(sa_sync_conn, "10.9/apc-d")
    university, lab = (
        sa_sync_conn.execute(
            text(
                "INSERT INTO structures (code, name, structure_type)"
                " VALUES (:c, :n, CAST(:t AS structure_type)) RETURNING id"
            ),
            {"c": code, "n": name, "t": kind},
        ).scalar_one()
        for code, name, kind in (
            ("TEST_APC_U", "Université test APC", "universite"),
            ("TEST_APC_L", "Labo test APC", "labo"),
        )
    )
    sa_sync_conn.execute(
        text(
            "INSERT INTO structure_name_forms (structure_id, form_text, is_word_boundary, requires_context_of)"
            " VALUES (:u, 'universite test apc', false, NULL), (:l, 'ltapc', true, ARRAY[:u])"
        ),
        {"u": university, "l": lab},
    )
    payment = {
        **_payment("10.9/apc-d", institution="Université Test APC", open_access_fee=False),
        "lab_name": "LTAPC",
    }

    stats = import_payments(sa_sync_conn, [payment], "f.csv")

    row = sa_sync_conn.execute(
        text(
            "SELECT lab_structure_id, budget_structure_id FROM apc_payments WHERE doi = '10.9/apc-d'"
        )
    ).one()
    assert (row.lab_structure_id, row.budget_structure_id) == (lab, university)
    assert all(u.label not in ("LTAPC", "Université Test APC") for u in stats.unresolved)


def test_frais_d_open_access_et_hors_oa_distincts(sa_sync_conn):
    _publication(sa_sync_conn, "10.9/apc-c")

    stats = import_payments(
        sa_sync_conn,
        [
            _payment("10.9/apc-c", open_access_fee=True),
            _payment("10.9/apc-c", open_access_fee=False),
        ],
        "f.csv",
    )

    assert stats.inserted == 2
