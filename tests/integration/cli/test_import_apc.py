"""Écriture des frais de publication : périmètre de la base, idempotence, rattachements."""

from sqlalchemy import text

from interfaces.cli.imports.import_apc import import_payments
from pipeline.transformation.publications.store import PublicationStore
from tests.integration.helpers.structures import insert_structure, insert_structure_name_form


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
        "publication_year": 2022,
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
    return PublicationStore(conn).create(
        title="t",
        title_normalized="t",
        doc_type="article",
        publication_year=2022,
        doi=doi,
        oa_status="unknown",
    )


def _count(conn) -> int:
    return conn.execute(text("SELECT count(*) FROM apc_payments")).scalar_one()


def test_seuls_les_doi_de_la_base_sont_importes(sa_sync_conn):
    publication = _publication(sa_sync_conn, "10.9/apc-a")

    stats = import_payments(
        sa_sync_conn, [_payment("10.9/apc-a"), _payment("10.9/hors-base"), _payment(None)], "f.csv"
    )

    assert (stats.read, stats.in_base, stats.inserted) == (3, 1, 1)
    assert (
        sa_sync_conn.execute(
            text("SELECT publication_id FROM apc_payments WHERE doi = '10.9/apc-a'")
        ).scalar_one()
        == publication
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
    university = insert_structure(
        sa_sync_conn, "TEST_APC_U", name="Université test APC", structure_type="universite"
    )
    lab = insert_structure(sa_sync_conn, "TEST_APC_L", name="Labo test APC")
    insert_structure_name_form(sa_sync_conn, university, form_text="universite test apc")
    insert_structure_name_form(
        sa_sync_conn, lab, form_text="ltapc", requires_context_of=[university]
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


def test_payeur_designe_par_son_ror(sa_sync_conn):
    """Le payeur prend le nom du registre ROR. Un ROR absent du registre sert de nom : le réimport reste sans doublon."""
    _publication(sa_sync_conn, "10.9/apc-e")
    sa_sync_conn.execute(
        text("""
            INSERT INTO ror_organizations (ror_id, name, country_code, types, status)
            VALUES ('0testapc1', 'Université ROR test APC', 'fr', ARRAY['education']::ror_type[], 'active')
        """)
    )
    payments = [
        {**_payment("10.9/apc-e", amount=100.0), "institution": None, "payer_ror": "0testapc1"},
        {**_payment("10.9/apc-e", amount=200.0), "institution": None, "payer_ror": "0testapc2"},
    ]

    import_payments(sa_sync_conn, payments, "f.csv")
    second = import_payments(sa_sync_conn, payments, "f.csv")

    institutions = sa_sync_conn.execute(
        text("SELECT institution FROM apc_payments WHERE doi = '10.9/apc-e' ORDER BY amount_eur_ht")
    ).scalars()
    assert list(institutions) == ["Université ROR test APC", "0testapc2"]
    assert second.inserted == 0


def test_paiements_de_l_etablissement_hors_de_la_base(sa_sync_conn):
    """Un paiement à DOI de l'établissement entre sans publication, puis la rejoint quand elle entre dans la base. Le réimport reste sans doublon."""
    ours = lambda p: p["institution"] == "Université test"  # noqa: E731
    payments = [
        _payment("10.9/hors-base-ours", institution="Université test"),
        _payment("10.9/hors-base-other", institution="CNRS"),
        _payment(None, institution="Université test"),
    ]

    first = import_payments(sa_sync_conn, payments, "f.csv", from_institution=ours)
    second = import_payments(sa_sync_conn, payments, "f.csv", from_institution=ours)

    assert (first.outside_base, first.inserted, second.inserted) == (1, 1, 0)
    assert sa_sync_conn.execute(text("SELECT doi FROM apc_payments")).scalars().all() == [
        "10.9/hors-base-ours"
    ]
    publication = _publication(sa_sync_conn, "10.9/hors-base-ours")
    import_payments(sa_sync_conn, [], "f.csv")
    assert (
        sa_sync_conn.execute(
            text("SELECT publication_id FROM apc_payments WHERE doi = '10.9/hors-base-ours'")
        ).scalar_one()
        == publication
    )


def test_reponse_de_l_etablissement_l_emporte_sur_open_apc(sa_sync_conn):
    """Un frais d'open access Open APC d'un article que la réponse de son payeur décrit déjà est retiré, quel que soit l'ordre des imports. Un autre payeur garde le sien."""
    _publication(sa_sync_conn, "10.9/apc-prio")
    university = insert_structure(
        sa_sync_conn, "TEST_APC_PRIO", name="Université prio APC", structure_type="universite"
    )
    insert_structure_name_form(sa_sync_conn, university, form_text="universite prio apc")
    response = {
        **_payment("10.9/apc-prio", institution="Université prio APC", amount=2390.0),
        "lab_name": "LPRIO",
    }
    open_apc = _payment("10.9/apc-prio", institution="Université prio APC", amount=2445.0)
    other_payer = _payment("10.9/apc-prio", institution="CNRS", amount=800.0)

    import_payments(sa_sync_conn, [open_apc, other_payer], "apc_de.csv")
    first = import_payments(sa_sync_conn, [response], "reponse.csv")
    again = import_payments(sa_sync_conn, [open_apc, other_payer], "apc_de.csv")

    assert (first.superseded, again.superseded) == (1, 1)
    amounts = sa_sync_conn.execute(
        text("SELECT amount_eur_ht FROM apc_payments WHERE doi = '10.9/apc-prio' ORDER BY 1")
    ).scalars()
    assert [float(a) for a in amounts] == [800.0, 2390.0]


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
