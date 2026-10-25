"""Liens d'accès d'une publication (`domain.publications.access`)."""

from domain.publications.access import Access, AccessLink, Copy, access


def _copy(url, *, version=None, is_oa=True, platform=None, described=False, arrival=1) -> Copy:
    return Copy(
        url=url,
        version=version,
        is_oa=is_oa,
        platform=platform,
        described_by_platform=described,
        arrival=arrival,
    )


def test_version_puis_ordre_d_arrivee():
    result = access(
        [
            _copy("https://hal.science/hal-1", platform="HAL", described=True, arrival=1),
            _copy(
                "https://arxiv.org/abs/1", version="submittedVersion", platform="arXiv", arrival=3
            ),
            _copy("https://doi.org/10.1/x", version="publishedVersion", arrival=2),
        ]
    )
    # La copie que désigne le DOI est l'adresse d'accès, sans figurer parmi les liens.
    assert result == Access(
        url="https://doi.org/10.1/x",
        links=[
            AccessLink("arXiv", "https://arxiv.org/abs/1"),
            AccessLink("HAL", "https://hal.science/hal-1"),
        ],
    )


def test_une_copie_par_plateforme():
    links = access(
        [
            _copy("https://arxiv.org/abs/1", platform="arXiv", arrival=1),
            _copy(
                "https://arxiv.org/abs/1v2", version="submittedVersion", platform="arXiv", arrival=2
            ),
        ]
    ).links
    assert links == [AccessLink("arXiv", "https://arxiv.org/abs/1v2")]


def test_les_copies_fermees_sont_ecartees():
    assert access([_copy("https://pubmed.ncbi.nlm.nih.gov/1", is_oa=False)]) == Access(None, [])


def test_hal_decide_de_l_ouverture_de_ses_notices():
    """OpenAlex dit ouverte une notice HAL sans fichier : la notice que donne HAL l'emporte."""
    copies = [
        _copy("https://hal.science/hal-1", platform="HAL", described=True, is_oa=False),
        _copy("https://hal.science/hal-1", version="submittedVersion", platform="HAL", arrival=2),
    ]
    assert access(copies) == Access(None, [])


def test_seule_une_adresse_web_compte():
    copies = [
        _copy("javascript:alert(1)"),
        _copy("ftp://x.org/a"),
        _copy("https://x.org/a", arrival=2),
    ]
    assert access(copies) == Access("https://x.org/a", [AccessLink("x.org", "https://x.org/a")])
