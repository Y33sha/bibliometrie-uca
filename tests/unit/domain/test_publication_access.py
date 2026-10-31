"""Liens d'accès d'une publication (`domain.publications.access`)."""

from domain.platforms.registry import ARXIV, HAL, ZENODO
from domain.publications.access import Access, AccessLink, Copy, access, access_url

_KNOWN = {p.name: p for p in (ARXIV, HAL, ZENODO)}
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
        embargoed=False,
        described_by_platform=described,
        arrival=arrival,
    )


def _access(copies) -> Access:
    return access(copies, doi=_DOI)


def test_version_puis_ordre_d_arrivee():
    result = _access(
        [
            _copy("https://hal.science/hal-1", platform="HAL", described=True, arrival=1),
            _copy(
                "https://arxiv.org/abs/1", version="submittedVersion", platform="arXiv", arrival=3
            ),
            _copy("https://doi.org/10.1/x", version="publishedVersion", arrival=2),
        ]
    )
    # La copie désignée par le DOI est l'adresse d'accès, sans figurer parmi les liens.
    assert result == Access(
        url="https://doi.org/10.1/x",
        links=[
            AccessLink("arXiv", "https://arxiv.org/abs/1", known=True),
            AccessLink("HAL", "https://hal.science/hal-1", known=True),
        ],
    )


def test_une_copie_par_plateforme():
    links = _access(
        [
            _copy("https://arxiv.org/abs/1", platform="arXiv", arrival=1),
            _copy(
                "https://arxiv.org/abs/1v2", version="submittedVersion", platform="arXiv", arrival=2
            ),
        ]
    ).links
    assert links == [AccessLink("arXiv", "https://arxiv.org/abs/1v2", known=True)]


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
        AccessLink("HAL", "https://hal.science/hal-01651302", known=True)
    ]


def test_seule_une_adresse_web_compte():
    copies = [
        _copy("javascript:alert(1)"),
        _copy("ftp://x.org/a"),
        _copy("https://x.org/a", arrival=2),
    ]
    assert _access(copies) == Access(
        "https://x.org/a", [AccessLink("x.org", "https://x.org/a", known=False)]
    )


def test_un_depot_hors_registre_est_inconnu():
    links = _access([_copy("https://escholarship.org/uc/item/1", platform="eScholarship")]).links
    assert links == [AccessLink("eScholarship", "https://escholarship.org/uc/item/1", known=False)]


def test_une_copie_designee_par_un_autre_doi_figure_sur_sa_plateforme():
    """La copie Zenodo, désignée par son propre DOI, figure ; celle au DOI de la publication et celle sans plateforme sont écartées."""
    links = _access(
        [
            _copy("https://doi.org/10.1/X", version="publishedVersion", platform="Dépôt"),
            _copy("https://doi.org/10.5281/zenodo.1", platform="Zenodo", arrival=2),
            _copy("https://doi.org/10.9/y", arrival=3),
        ]
    ).links
    assert links == [AccessLink("Zenodo", "https://doi.org/10.5281/zenodo.1", known=True)]


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
        links=[AccessLink("Zenodo", "https://doi.org/10.5281/zenodo.8278818", known=True)],
    )


def test_une_plateforme_du_registre_porte_le_nom_du_registre():
    copy = Copy(
        url="https://zenodo.org/records/1",
        version=None,
        is_oa=True,
        platform="Zenodo (CERN European Organization for Nuclear Research)",
        known_platform=ZENODO,
        platform_type=ZENODO.platform_type,
        license=None,
        embargoed=False,
        described_by_platform=False,
        arrival=1,
    )
    assert _access([copy]).links == [AccessLink("Zenodo", copy.url, known=True)]


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
