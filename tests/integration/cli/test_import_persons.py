"""Import RH : lecture d'un export, rattachement des agents, attributs, périodes de présence, correspondance des unités."""

import datetime

import pytest
from sqlalchemy import text

from domain.persons.hr_periods import HrPeriod
from interfaces.cli.imports.import_persons import (
    HrExport,
    HrRow,
    OlderExportError,
    RhImportOutcome,
    group_agents,
    import_export,
    parse_rows,
)
from pipeline.transformation.structures.perimeter import refresh_perimeter_structures
from tests.integration.helpers.persons import insert_hr_period, insert_hr_record, insert_person
from tests.integration.helpers.structures import (
    insert_persons_perimeter,
    insert_structure,
    insert_structure_name_form,
    insert_tutelle,
)

D = datetime.date

_SIHAM_HEADERS = [
    "Matricule SIHAM",
    "Nom usuel - Individu",
    "Prénom - Individu",
    "_ENS/BIATSS",
    "Statut",
    "Corps",
    "Grade",
    "Date d'effet - Principales/Hiérarchique",
    "Date de fin - Principales/Hiérarchique",
    "Unité Organisationnelle (lib abr) - Principales/Hiérarchique",
    "Date d'effet - Répartition organisationnelle",
    "Date de fin - Répartition organisationnelle",
    "Unité Organisationnelle (lib abr) - Répartition organisationnelle",
    "_Mail",
]


def _siham_rows(*rows: list[str]) -> list[list[str]]:
    title = [
        "DPCG",
        "Carrière des agents",
        (
            "Données issues de SIHAMDate début d'observation : 15/12/2025"
            "Date fin d'observation : 02/11/2026Dernière exécution : 02/11/2026"
        ),
    ]
    return [title, [], _SIHAM_HEADERS, *rows]


def _export(*agents: HrRow, start=D(2025, 12, 15), end=D(2026, 11, 2)) -> HrExport:
    return HrExport(start, end, list(agents))


def _periods(conn, person_id: int) -> list[tuple]:
    return [
        tuple(r)
        for r in conn.execute(
            text(
                "SELECT unit_label, start_date, end_date, structure_id FROM hr_periods "
                "WHERE person_id = :p ORDER BY unit_label, start_date"
            ),
            {"p": person_id},
        )
    ]


def _record(conn, person_id: int):
    return conn.execute(
        text("SELECT * FROM hr_records WHERE person_id = :p"), {"p": person_id}
    ).one()


def _person_of(conn, siham_id: str) -> int:
    return conn.execute(
        text("SELECT person_id FROM hr_records WHERE siham_id = :s"), {"s": siham_id}
    ).scalar_one()


# Lecture


def test_lecture_d_un_export_siham():
    export = parse_rows(
        _siham_rows(
            [
                "UCA01",
                "DURAND",
                "MARIE",
                "ENSEIG",
                "Titulaire",
                "MCF",
                "MCF CN",
                "01/01/2021",
                "",
                "UFR X",
                "01/09/2024",
                "",
                "LAB Y",
                "Marie.Durand@uca.fr",
            ]
        )
    )
    assert (export.window_start, export.window_end) == (D(2025, 12, 15), D(2026, 11, 2))
    [row] = export.rows
    assert (row.siham_id, row.email, row.staff_category, row.corps, row.grade) == (
        "UCA01",
        "Marie.Durand@uca.fr",
        "ENSEIG",
        "MCF",
        "MCF CN",
    )
    assert set(row.periods) == {
        HrPeriod("LAB Y", D(2024, 9, 1), None),
        HrPeriod("UFR X", D(2021, 1, 1), None),
    }


def test_lecture_d_un_export_a_date_d_observation_unique():
    rows = [
        [
            "DPCG",
            "Carrière des agents au 15/12/2025",
            "Données issues de SIHAM\nDate d'observation : 15/12/2025",
        ],
        [],
        [
            "Matricule SIHAM",
            "Nom usuel - Individu",
            "Prénom - Individu",
            "_Mail",
            "Unité Organisationnelle (lib abr) - Principales/Hiérarchique",
            "Corps ou statut",
            "Date de début dans le corps ou début de contrat",
            "Date de fin dans le corps ou début de contrat",
        ],
        ["UCA01", "DURAND", "MARIE", "m@uca.fr", "UFR X", "MCF", "01/09/2005", ""],
    ]
    export = parse_rows(rows)
    assert export.window_start == export.window_end == D(2025, 12, 15)
    [row] = export.rows
    assert row.corps == "MCF"
    assert row.periods == (HrPeriod("UFR X", D(2005, 9, 1), None),)


def test_lignes_d_un_agent_reunies_avec_les_attributs_les_plus_recents():
    rows = [
        HrRow(
            "Durand",
            "Marie",
            siham_id="UCA01",
            grade="CN",
            periods=(HrPeriod("LAB", D(2026, 1, 1), D(2026, 5, 31)),),
        ),
        HrRow(
            "Durand",
            "Marie",
            siham_id="UCA01",
            grade="HC",
            periods=(HrPeriod("LAB", D(2026, 6, 1), None),),
        ),
        HrRow("Sans", "Clé"),
    ]
    agents, unkeyed = group_agents(rows)
    assert unkeyed == 1
    [agent] = agents
    assert agent.grade == "HC"
    assert agent.periods == (HrPeriod("LAB", D(2026, 1, 1), None),)


# Rattachement et attributs


def test_agent_inconnu_cree_avec_sa_fiche_et_ses_periodes(sa_sync_conn):
    agent = HrRow(
        "Durand",
        "Marie",
        siham_id="UCA01",
        email="m@uca.fr",
        staff_category="BIATSS",
        corps="IGE",
        periods=(HrPeriod("UNITE INCONNUE", D(2024, 1, 1), None),),
    )
    counts = import_export(sa_sync_conn, _export(agent))
    assert counts[RhImportOutcome.CREATED] == 1
    person = _person_of(sa_sync_conn, "UCA01")
    record = _record(sa_sync_conn, person)
    assert (record.staff_category, record.corps, record.hr_export_date) == (
        "BIATSS",
        "IGE",
        D(2026, 11, 2),
    )
    assert _periods(sa_sync_conn, person) == [("UNITE INCONNUE", D(2024, 1, 1), None, None)]


def test_agent_rattache_par_matricule_sans_creation(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Durand", first_name="Marie")
    insert_hr_record(sa_sync_conn, person, email="ancien@uca.fr")
    sa_sync_conn.execute(
        text("UPDATE hr_records SET siham_id = 'UCA01' WHERE person_id = :p"), {"p": person}
    )

    counts = import_export(
        sa_sync_conn, _export(HrRow("Durand", "Marie", siham_id="UCA01", email="m@uca.fr"))
    )

    assert counts[RhImportOutcome.BY_SIHAM_ID] == 1
    assert _record(sa_sync_conn, person).email == "m@uca.fr"


def test_agent_rattache_par_email_recoit_son_matricule(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Durand", first_name="Marie")
    insert_hr_record(sa_sync_conn, person, email="Marie.Durand@uca.fr")

    counts = import_export(
        sa_sync_conn, _export(HrRow("Autre", "Nom", siham_id="UCA01", email="marie.durand@uca.fr"))
    )

    assert counts[RhImportOutcome.BY_EMAIL] == 1
    assert _record(sa_sync_conn, person).siham_id == "UCA01"


def test_attribut_absent_de_l_export_conserve(sa_sync_conn):
    import_export(sa_sync_conn, _export(HrRow("Durand", "Marie", siham_id="UCA01", grade="HC")))
    import_export(sa_sync_conn, _export(HrRow("Durand", "Marie", siham_id="UCA01", corps="MCF")))

    record = _record(sa_sync_conn, _person_of(sa_sync_conn, "UCA01"))
    assert (record.corps, record.grade) == ("MCF", "HC")


def test_fiche_ajoutee_a_l_unique_homonyme_sans_fiche(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Durand", first_name="Marie-Anne")

    counts = import_export(sa_sync_conn, _export(HrRow("DURAND", "MARIE ANNE", siham_id="UCA01")))

    assert counts[RhImportOutcome.BY_NAME] == 1
    assert _person_of(sa_sync_conn, "UCA01") == person


@pytest.mark.parametrize(
    "homonymes",
    [
        pytest.param([{}, {}], id="deux homonymes"),
        pytest.param([{"exclusion": "not_a_person"}], id="homonyme exclu"),
    ],
)
def test_personne_creee_sans_homonyme_unique_disponible(sa_sync_conn, homonymes):
    existing = {
        insert_person(sa_sync_conn, "Durand", first_name="Marie", **kwargs) for kwargs in homonymes
    }

    counts = import_export(sa_sync_conn, _export(HrRow("Durand", "Marie", siham_id="UCA01")))

    assert counts[RhImportOutcome.CREATED] == 1
    assert _person_of(sa_sync_conn, "UCA01") not in existing


def test_homonyme_deja_rh_laisse_creer_la_personne(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Durand", first_name="Marie")
    insert_hr_record(sa_sync_conn, person, email="autre@uca.fr")

    counts = import_export(sa_sync_conn, _export(HrRow("Durand", "Marie", siham_id="UCA01")))

    assert counts[RhImportOutcome.CREATED] == 1


def test_prenom_a_initiale_sans_rattachement_a_l_homonyme(sa_sync_conn):
    insert_person(sa_sync_conn, "Durand", first_name="Jean L.")

    counts = import_export(sa_sync_conn, _export(HrRow("Durand", "Jean L.", siham_id="UCA01")))

    assert counts[RhImportOutcome.CREATED] == 1


@pytest.mark.parametrize(
    "agent",
    [
        pytest.param(HrRow("FRANCOIS", "HELENE", siham_id="UCA01"), id="par matricule"),
        pytest.param(HrRow("FRANCOIS", "HELENE", email="h@uca.fr"), id="par email"),
    ],
)
def test_nom_corrige_a_la_main_conserve(sa_sync_conn, agent):
    """Le nom de la personne reste celui en base, accents et cédilles compris."""
    person = insert_person(sa_sync_conn, "François", first_name="Hélène")
    insert_hr_record(sa_sync_conn, person, email="h@uca.fr")
    sa_sync_conn.execute(
        text("UPDATE hr_records SET siham_id = 'UCA01' WHERE person_id = :p"), {"p": person}
    )

    import_export(sa_sync_conn, _export(agent))

    name = sa_sync_conn.execute(
        text("SELECT last_name, first_name FROM persons WHERE id = :p"), {"p": person}
    ).one()
    assert tuple(name) == ("François", "Hélène")


def test_export_anterieur_au_dernier_importe_refuse(sa_sync_conn):
    import_export(sa_sync_conn, _export(HrRow("Durand", "Marie", siham_id="UCA01")))
    with pytest.raises(OlderExportError):
        import_export(
            sa_sync_conn,
            _export(
                HrRow("Durand", "Marie", siham_id="UCA01"), start=D(2025, 1, 1), end=D(2025, 1, 1)
            ),
        )


# Périodes


def test_periode_en_base_prolongee_par_l_export(sa_sync_conn):
    person = insert_person(sa_sync_conn, "Durand", first_name="Marie")
    insert_hr_record(sa_sync_conn, person, email="m@uca.fr")
    insert_hr_period(sa_sync_conn, person, unit_label="UFR X", start_date=D(2005, 9, 1))

    import_export(
        sa_sync_conn,
        _export(
            HrRow(
                "Durand",
                "Marie",
                email="m@uca.fr",
                periods=(HrPeriod("UFR X", D(2019, 1, 1), D(2025, 12, 31)),),
            )
        ),
    )

    assert _periods(sa_sync_conn, person) == [("UFR X", D(2005, 9, 1), D(2025, 12, 31), None)]


# Correspondance des unités


def test_unite_rattachee_par_son_sigle(sa_sync_conn):
    lab = insert_structure(
        sa_sync_conn, "lab_ressources", name="UMR Ressources", acronym="Ressources"
    )

    import_export(
        sa_sync_conn,
        _export(
            HrRow(
                "Durand",
                "Marie",
                siham_id="UCA01",
                periods=(HrPeriod("RESSOURCES", D(2024, 1, 1), None),),
            )
        ),
    )

    assert _periods(sa_sync_conn, _person_of(sa_sync_conn, "UCA01"))[0][3] == lab


def test_unite_reconnue_avec_le_perimetre_des_personnes_pour_contexte(sa_sync_conn):
    """Libellé suffixé : la forme du laboratoire exige le contexte de l'université, donné par le périmètre. L'université, racine du périmètre, reste hors résultat."""
    root = insert_persons_perimeter(sa_sync_conn, "uni")
    lab = insert_structure(sa_sync_conn, "lab_x", name="Laboratoire X", acronym="LABX")
    insert_tutelle(sa_sync_conn, root, child_id=lab)
    insert_structure_name_form(sa_sync_conn, lab, form_text="labx", requires_context_of=[root])
    insert_structure_name_form(sa_sync_conn, root, form_text="uni")
    refresh_perimeter_structures(sa_sync_conn)

    import_export(
        sa_sync_conn,
        _export(
            HrRow(
                "Durand",
                "Marie",
                siham_id="UCA01",
                periods=(
                    HrPeriod("LABX - Sciences", D(2024, 1, 1), None),
                    HrPeriod("UNI Services", D(2024, 1, 1), None),
                ),
            )
        ),
    )

    structures = {
        label: sid for label, _, _, sid in _periods(sa_sync_conn, _person_of(sa_sync_conn, "UCA01"))
    }
    assert structures == {"LABX - Sciences": lab, "UNI Services": None}
