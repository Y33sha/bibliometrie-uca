"""Liens d'accès d'une publication (`domain.publications.access`)."""

from dataclasses import replace

import pytest

from domain.platforms.platform import ARCHIVE_TYPES, PlatformType
from domain.platforms.registry import HAL, KNOWN_PLATFORMS
from domain.publications.access import (
    Access,
    AccessLink,
    Copy,
    access,
    access_url,
    registered_url_copy,
)

_KNOWN = {p.name: p for p in KNOWN_PLATFORMS if p.name in {"arXiv", "HAL", "Zenodo"}}
_ARXIV, _ZENODO = _KNOWN["arXiv"], _KNOWN["Zenodo"]
_DOI = "10.1/x"


def _copy(url, *, version=None, is_oa=True, platform=None, described=False, arrival=1) -> Copy:
    known = _KNOWN.get(platform or "")
    return Copy(
        url=url,
        version=version,
        is_oa=is_oa,
        platform=platform,
        known_platform=known,
        platform_type=known.platform_type if known else None,
        license=None,
        described_by_platform=described,
        arrival=arrival,
    )


def _access(copies) -> Access:
    return access(copies, doi=_DOI)


def test_l_editeur_puis_les_plateformes_a_icone_puis_les_autres():
    result = _access(
        [
            _copy("https://hal.science/hal-1", platform="HAL", described=True, arrival=3),
            _copy("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/", version="acceptedVersion"),
            _copy("https://doi.org/10.1/x", version="publishedVersion", arrival=2),
        ]
    )
    # La copie désignée par le DOI est l'adresse d'accès, sans figurer parmi les liens.
    assert result == Access(
        url="https://doi.org/10.1/x",
        links=[
            AccessLink("HAL", "https://hal.science/hal-1", icon=HAL.icon),
            AccessLink(
                "ncbi.nlm.nih.gov",
                "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1/",
                icon=None,
            ),
        ],
    )


def test_la_copie_de_l_editeur_passe_avant_une_meilleure_version_sur_une_plateforme():
    result = _access(
        [
            _copy("https://hal.science/hal-1", version="publishedVersion", platform="HAL"),
            _copy("https://doi.org/10.1/X", version="submittedVersion", arrival=2),
        ]
    )
    assert result.url == "https://doi.org/10.1/X"


def test_une_version_editeur_passe_avant_une_plateforme_a_icone():
    """Le Handle d'une archive institutionnelle, en version éditeur, passe avant HAL en version acceptée."""
    result = _access(
        [
            _copy(
                "http://hdl.handle.net/20.500.1/1", version="publishedVersion", platform="Handle"
            ),
            _copy(
                "https://hal.science/hal-1", version="acceptedVersion", platform="HAL", arrival=2
            ),
        ]
    )
    assert result.url == "http://hdl.handle.net/20.500.1/1"
    assert [link.icon for link in result.links] == [None, HAL.icon]


def test_une_plateforme_a_icone_passe_avant_une_meilleure_version_sans_icone():
    """Hors version éditeur, l'icône prime sur la version : HAL soumis passe avant une copie acceptée sans icône."""
    result = _access(
        [
            _copy("https://example.org/1", version="acceptedVersion"),
            _copy(
                "https://hal.science/hal-1", version="submittedVersion", platform="HAL", arrival=2
            ),
        ]
    )
    assert result.url == "https://hal.science/hal-1"


def test_la_version_editeur_d_un_preprint_reste_avec_les_preprints():
    """La « version publiée » d'un preprint arXiv passe après HAL en version acceptée."""
    result = _access(
        [
            _copy("https://arxiv.org/abs/1", version="publishedVersion", platform="arXiv"),
            _copy(
                "https://hal.science/hal-1", version="acceptedVersion", platform="HAL", arrival=2
            ),
        ]
    )
    assert result.url == "https://hal.science/hal-1"


def test_les_copies_d_un_preprint_passent_apres_les_autres():
    """La copie arXiv soumise et la copie du dépôt HAL du preprint passent après la copie Zenodo, de version inconnue."""
    preprint_hal = replace(
        _copy("https://hal.science/hal-2", platform="HAL", described=True, arrival=1),
        preprint_record=True,
    )
    result = _access(
        [
            _copy(
                "https://arxiv.org/abs/1", version="submittedVersion", platform="arXiv", arrival=1
            ),
            preprint_hal,
            _copy("https://zenodo.org/records/1", platform="Zenodo", arrival=3),
        ]
    )
    assert result.url == "https://zenodo.org/records/1"
    assert [link.label for link in result.links] == ["Zenodo", "arXiv", "HAL"]


def test_un_preprint_seul_donne_l_adresse_d_acces():
    copy = _copy("https://arxiv.org/abs/1", version="submittedVersion", platform="arXiv")
    assert _access([copy]).url == "https://arxiv.org/abs/1"


def test_une_copie_par_plateforme():
    links = _access(
        [
            _copy("https://arxiv.org/abs/1", platform="arXiv", arrival=1),
            _copy(
                "https://arxiv.org/abs/1v2", version="submittedVersion", platform="arXiv", arrival=2
            ),
        ]
    ).links
    assert links == [AccessLink("arXiv", "https://arxiv.org/abs/1v2", icon=_ARXIV.icon)]


def test_les_copies_fermees_sont_ecartees():
    assert _access([_copy("https://pubmed.ncbi.nlm.nih.gov/1", is_oa=False)]) == Access(None, [])


def test_hal_decide_de_l_ouverture_de_ses_copies():
    """OpenAlex dit ouverte une copie HAL sans fichier : la copie donnée par HAL l'emporte."""
    copies = [
        _copy("https://hal.science/hal-01607327", platform="HAL", described=True, is_oa=False),
        _copy(
            "https://hal.science/hal-01607327",
            version="submittedVersion",
            platform="HAL",
            arrival=2,
        ),
    ]
    assert _access(copies) == Access(None, [])


def test_hal_decide_seulement_pour_ses_propres_depots():
    """OpenAlex réunit deux dépôts HAL ; seul le premier a son enregistrement source HAL dans la publication."""
    copies = [
        _copy("https://hal.science/hal-01607327v1", platform="HAL", described=True, is_oa=False),
        _copy("https://hal.science/hal-01607327", platform="HAL", arrival=2),
        _copy("https://hal.science/hal-01651302", platform="HAL", arrival=2),
    ]
    assert _access(copies).links == [
        AccessLink("HAL", "https://hal.science/hal-01651302", icon=HAL.icon)
    ]


def test_seule_une_adresse_web_compte():
    copies = [
        _copy("javascript:alert(1)"),
        _copy("ftp://x.org/a"),
        _copy("https://x.org/a", arrival=2),
    ]
    assert _access(copies) == Access(
        "https://x.org/a", [AccessLink("x.org", "https://x.org/a", icon=None)]
    )


def test_un_depot_hors_registre_est_inconnu():
    links = _access([_copy("https://escholarship.org/uc/item/1", platform="eScholarship")]).links
    assert links == [AccessLink("eScholarship", "https://escholarship.org/uc/item/1", icon=None)]


def test_une_copie_designee_par_un_autre_doi_figure_sur_sa_plateforme():
    """La copie Zenodo, désignée par son propre DOI, figure ; celle au DOI de la publication et celle sans plateforme sont écartées."""
    links = _access(
        [
            _copy("https://doi.org/10.1/X", version="publishedVersion", platform="Dépôt"),
            _copy("https://doi.org/10.5281/zenodo.1", platform="Zenodo", arrival=2),
            _copy("https://doi.org/10.9/y", arrival=3),
        ]
    ).links
    assert links == [AccessLink("Zenodo", "https://doi.org/10.5281/zenodo.1", icon=_ZENODO.icon)]


def test_le_doi_de_la_publication_sur_une_plateforme_du_registre_figure_parmi_les_liens():
    """Publication déposée sur Zenodo : son DOI mène à Zenodo, pas à un éditeur."""
    result = access(
        [
            _copy("https://doi.org/10.5281/zenodo.8278818", platform="Zenodo", arrival=1),
            _copy("https://doi.org/10.5281/zenodo.8278819", platform="Zenodo", arrival=2),
        ],
        doi="10.5281/zenodo.8278818",
    )
    assert result == Access(
        url="https://doi.org/10.5281/zenodo.8278818",
        links=[AccessLink("Zenodo", "https://doi.org/10.5281/zenodo.8278818", icon=_ZENODO.icon)],
    )


def test_le_doi_de_la_publication_chez_un_editeur_reste_hors_des_liens():
    copy = replace(
        _copy("https://doi.org/10.48611/isbn.978-2", platform="Classiques Garnier"),
        platform_type=PlatformType.PUBLISHER_PLATFORM,
    )
    assert access([copy], doi="10.48611/isbn.978-2") == Access(
        url="https://doi.org/10.48611/isbn.978-2", links=[]
    )


def test_une_plateforme_du_registre_porte_le_nom_du_registre():
    copy = Copy.of_location(
        "https://zenodo.org/records/1",
        version=None,
        declared_oa=True,
        arrival=1,
        source_platform="Zenodo (CERN European Organization for Nuclear Research)",
    )
    assert (copy.known_platform, copy.platform_type) == (_ZENODO, _ZENODO.platform_type)
    assert _access([copy]).links == [AccessLink("Zenodo", copy.url, icon=_ZENODO.icon)]


def test_une_plateforme_hors_du_registre_garde_le_nom_et_le_type_donnes_par_la_source():
    copy = Copy.of_location(
        "https://escholarship.org/uc/item/1",
        version=None,
        declared_oa=True,
        arrival=1,
        source_platform="eScholarship",
        source_platform_type=PlatformType.REPOSITORY,
    )
    assert (copy.platform, copy.known_platform, copy.platform_type) == (
        "eScholarship",
        None,
        PlatformType.REPOSITORY,
    )


def test_une_copie_sous_embargo_est_fermee():
    copy = Copy.of_location(
        "https://hal.science/hal-1/document",
        version=None,
        declared_oa=True,
        arrival=1,
        embargoed=True,
    )
    assert copy.is_oa is False


def test_seule_la_copie_hal_d_un_enregistrement_hal_est_decrite_par_sa_plateforme():
    def described(url, record_source):
        copy = Copy.of_location(
            url, version=None, declared_oa=True, arrival=1, record_source=record_source
        )
        return copy.described_by_platform

    assert described("https://hal.science/hal-1", "hal")
    assert not described("https://hal.science/hal-1", "openalex")
    assert not described("https://arxiv.org/abs/1", "hal")


def test_une_copie_garde_le_type_preprint_de_son_enregistrement_source():
    copy = Copy.of_location(
        "https://example.org/1",
        version=None,
        declared_oa=True,
        arrival=1,
        record_doc_type="preprint",
    )
    assert copy.of_preprint


def test_l_adresse_enregistree_d_un_pdf_donne_une_copie_ouverte_de_l_editeur():
    copy = registered_url_copy("http://isyou.info/jowua/papers/jowua-v12n1-6.PDF?dl=1")
    assert copy is not None
    assert (copy.is_oa, copy.version, copy.platform_type, copy.license) == (
        True,
        "publishedVersion",
        None,
        None,
    )


def test_l_adresse_enregistree_d_une_page_ne_donne_aucune_copie():
    assert registered_url_copy("https://www.techno-press.org/content/?page=article") is None
    assert registered_url_copy("https://e.org/pdf/12") is None
    assert registered_url_copy("https://www.researchsquare.com/article/rs-1/v1") is None


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/abs/2011.12961",
        "https://www.biorxiv.org/content/10.1101/2022.08.29.505639v1",
        "https://www.medrxiv.org/content/10.1101/2021.01.01.21249117v2",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123/",
    ],
)
def test_l_adresse_enregistree_d_une_plateforme_en_acces_libre_integral_donne_une_copie_ouverte(
    url,
):
    copy = registered_url_copy(url)
    assert copy is not None
    assert (copy.is_oa, copy.version, copy.platform_type in ARCHIVE_TYPES) == (True, None, True)


def test_la_copie_de_l_adresse_enregistree_passe_devant_une_copie_d_archive():
    pdf = registered_url_copy("https://www.cetjournal.it/cet/23/101/002.pdf")
    assert pdf is not None
    hal = _copy("https://hal.science/hal-1", platform="HAL", described=True, arrival=1)
    assert _access([hal, pdf]).url == pdf.url


def test_le_lien_d_acces_mene_a_la_meilleure_copie():
    url = "https://hal.science/hal-1"
    assert access_url(url, oa_status="green", doi=_DOI) == url


def test_le_lien_d_acces_d_une_publication_ouverte_sans_copie_mene_au_doi():
    assert access_url(None, oa_status="gold", doi=_DOI) == "https://doi.org/10.1/x"


def test_une_publication_de_statut_inconnu_sans_copie_n_a_pas_de_lien_d_acces():
    assert access_url(None, oa_status="unknown", doi=_DOI) is None


def test_une_publication_fermee_ou_sous_embargo_n_a_pas_de_lien_d_acces():
    assert access_url("https://hal.science/hal-1", oa_status="closed", doi=_DOI) is None
    assert access_url("https://hal.science/hal-1", oa_status="embargoed", doi=_DOI) is None
