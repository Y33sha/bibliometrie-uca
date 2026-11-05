"""Règles de rattachement d'un enregistrement source à sa revue (`domain.serials.attachment`)."""

from domain.serials.attachment import (
    KnownIssn,
    NewSerial,
    TitledSerial,
    choose_issnl,
    effective_issnl,
    match_by_title,
    match_in_publication,
    openalex_issnls,
    plan_issnl_serials,
)


def test_issn_l_du_sudoc_puis_d_openalex_puis_l_issn_lui_meme():
    openalex = {"1476-4687": "0028-0836"}
    assert effective_issnl("1476-4687", "0028-0836", {}) == "0028-0836"
    assert effective_issnl("1476-4687", None, openalex) == "0028-0836"
    assert effective_issnl("1476-4687", None, {}) == "1476-4687"


def test_issn_l_d_openalex_le_plus_frequent():
    issnls = openalex_issnls(
        [
            ("0028-0836", ("1476-4687",)),
            ("0028-0836", ("1476-4687",)),
            ("9999-9999", ("1476-4687",)),
        ]
    )
    assert issnls == {"0028-0836": "0028-0836", "1476-4687": "0028-0836", "9999-9999": "9999-9999"}


def test_plan_les_issn_d_un_issn_l_partagent_sa_revue():
    plan = plan_issnl_serials(
        {"0028-0836": KnownIssn(None, 7), "1476-4687": KnownIssn("0028-0836", None)}, {}, {}, []
    )
    assert plan.issnl_of == {"0028-0836": "0028-0836", "1476-4687": "0028-0836"}
    assert plan.serial_of == {"0028-0836": 7}


def test_plan_un_issn_annule_prend_l_issn_l_de_l_issn_qui_l_annule():
    plan = plan_issnl_serials(
        {"1111-1111": KnownIssn(None, None), "2222-2222": KnownIssn("3333-3333", 5)},
        {"1111-1111": "2222-2222"},
        {"1111-1111": "9999-9999"},
        [],
    )
    assert plan.issnl_of["1111-1111"] == "3333-3333"


def test_plan_revue_la_plus_frequente_parmi_les_issn():
    issns = {
        "1111-1111": KnownIssn("4444-4444", 1),
        "2222-2222": KnownIssn("4444-4444", 2),
        "3333-3333": KnownIssn("4444-4444", 2),
    }
    assert plan_issnl_serials(issns, {}, {}, []).serial_of == {"4444-4444": 2}


def test_plan_une_revue_va_a_un_seul_issn_l():
    """La revue désignée par la ligne d'un ISSN-L lui revient ; l'autre ISSN-L, dont un ISSN la tient aussi, reçoit une revue à créer."""
    issns = {
        "1111-1111": KnownIssn(None, 9),
        "2222-2222": KnownIssn(None, 9),
    }
    plan = plan_issnl_serials(issns, {}, {}, [(("2222-2222",), "Revue B")])
    assert plan.serial_of == {
        "1111-1111": 9,
        "2222-2222": NewSerial("issnl:2222-2222", "Revue B"),
    }


def test_plan_revue_a_creer_au_titre_le_plus_frequent_de_ses_series():
    issns = {"1111-1111": KnownIssn(None, None)}
    series = [(("1111-1111",), "Revue"), (("1111-1111",), "Revue"), (("1111-1111",), "REVUE")]
    assert plan_issnl_serials(issns, {}, {}, series).serial_of == {
        "1111-1111": NewSerial("issnl:1111-1111", "Revue")
    }


def test_plan_issn_l_sans_serie_ni_revue_sans_revue():
    issns = {"1111-1111": KnownIssn(None, None)}
    assert plan_issnl_serials(issns, {}, {}, [(("1111-1111",), None)]).serial_of == {}


def test_un_seul_issn_l_l_emporte_d_office():
    assert choose_issnl(None, {"0028-0836": "Nature"}) == "0028-0836"


def test_plusieurs_issn_l_departages_par_le_titre():
    """Cas réel : un article donne l'ISSN de « BMC Family Practice » et celui de son titre suivant."""
    candidates = {"1471-2296": "BMC family practice", "2731-4553": "BMC primary care"}
    assert choose_issnl("BMC Family Practice", candidates) == "1471-2296"
    assert choose_issnl("Autre titre", candidates) is None
    assert choose_issnl(None, candidates) is None


def test_titre_identique_avant_titre_compatible():
    """Cas réel : un article donne l'ISSN d'« INRAE Productions Animales » et celui de son titre précédent."""
    candidates = {
        "2824-3633": "INRAE productions animales",
        "2273-774X": "INRA productions animales",
    }
    assert choose_issnl("INRAE Productions Animales", candidates) == "2824-3633"


def test_seule_revue_a_issn_d_un_titre_quel_que_soit_l_editeur():
    assert match_by_title(30, [TitledSerial(3, 10)]) == 3


def test_seule_revue_a_issn_de_titre_compatible_dans_la_publication():
    serials = {41: "Journal of High Energy Physics", 489: "Physics Letters B"}
    assert match_in_publication("JHEP", serials) == 41
    assert match_in_publication("Phys.Lett.B", serials) == 489
    assert match_in_publication("Nature", serials) is None
    assert match_in_publication(None, serials) is None


def test_editeur_departage_les_revues_a_issn_d_un_titre():
    serials = [TitledSerial(1, 10), TitledSerial(2, 20), TitledSerial(3, None)]
    assert match_by_title(10, serials) == 1
    assert match_by_title(None, serials) is None
    assert match_by_title(30, serials) is None
