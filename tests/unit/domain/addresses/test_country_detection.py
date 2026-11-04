"""Nom de pays final et préséance entre les pays candidats d'une adresse."""

from domain.addresses.country_detection import (
    CountryDetectionMethod as M,
    CountryNames,
    retained_countries,
)

COUNTRY_NAMES = CountryNames(
    {
        "france": "fr",
        "kingdom": "xx",  # piège : sous-chaîne de « united kingdom »
        "united kingdom": "gb",
        "new zealand": "nz",
    }
)


def test_nom_de_pays_final():
    assert COUNTRY_NAMES.trailing_country("cnrs paris france") == "fr"


def test_le_plus_long_nom_de_pays_l_emporte():
    assert COUNTRY_NAMES.trailing_country("some lab london united kingdom") == "gb"


def test_texte_reduit_a_un_nom_de_pays():
    assert COUNTRY_NAMES.trailing_country("new zealand") == "nz"


def test_nom_de_pays_ailleurs_qu_a_la_fin_ignore():
    assert COUNTRY_NAMES.trailing_country("france avenue de paris") is None


def test_texte_vide_sans_pays():
    assert COUNTRY_NAMES.trailing_country("") is None


def test_sans_candidat_aucun_pays():
    assert retained_countries({}) == frozenset()


def test_le_premier_moyen_l_emporte():
    assert retained_countries({M.COUNTRY_NAME: ["ma"], M.INSTITUTION: ["fr"]}) == {"ma"}


def test_la_saisie_manuelle_l_emporte_toujours():
    candidates = {M.MANUAL: ["de"], M.COUNTRY_NAME: ["dk"], M.INSTITUTION: ["dk"], M.CITY: ["dk"]}
    assert retained_countries(candidates) == {"de"}


def test_deux_moyens_d_accord_contre_le_premier_l_emportent():
    """« Université Cadi Ayyad, Marrakech, Canada » : l'institution et la ville donnent le Maroc."""
    candidates = {M.COUNTRY_NAME: ["ca"], M.INSTITUTION: ["ma"], M.CITY: ["ma"]}
    assert retained_countries(candidates) == {"ma"}


def test_un_soutien_du_premier_pays_empeche_la_bascule():
    candidates = {
        M.COUNTRY_NAME: ["fr"],
        M.SOURCE_OPENALEX: ["gb"],
        M.INSTITUTION: ["gb"],
        M.CITY: ["fr"],
    }
    assert retained_countries(candidates) == {"fr"}


def test_les_pays_multiples_du_premier_moyen_sont_gardes():
    assert retained_countries({M.COUNTRY_NAME: ["fr", "re"]}) == {"fr", "re"}


def test_openalex_premier_moyen_garde_ses_pays_soutenus():
    """« Institut Pascal » : OpenAlex y ajoute l'Universidad Blas Pascal, en Argentine."""
    candidates = {M.SOURCE_OPENALEX: ["ar", "fr"], M.INSTITUTION: ["fr"]}
    assert retained_countries(candidates) == {"fr"}


def test_openalex_premier_moyen_sans_soutien_garde_ses_pays():
    assert retained_countries({M.SOURCE_OPENALEX: ["ar", "fr"]}) == {"ar", "fr"}


def test_un_autre_premier_moyen_garde_ses_pays_partiellement_soutenus():
    """Affiliations de plusieurs auteurs : la ville reconnaît seulement une partie des pays."""
    candidates = {M.INSTITUTION: ["fr", "gb", "gr"], M.CITY: ["fr"]}
    assert retained_countries(candidates) == {"fr", "gb", "gr"}


def test_le_premier_moyen_present_peut_etre_un_rang_inferieur():
    assert retained_countries({M.CITY: ["it"], M.SOURCE_SCANR: ["fr"]}) == {"it"}
