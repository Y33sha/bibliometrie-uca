from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
    normalize_identifiers,
)
from pipeline.ingestion.openalex.payload import (
    BULK_AUTHORSHIPS_CAP,
    OpenalexLocation,
    authors_may_be_truncated,
    extract_nnt_from_location,
    full_openalex_id,
    is_hal_location,
    is_repository_location,
    is_theses_fr_location,
    map_openalex_oa_status,
    names_publisher,
    names_serial,
    openalex_derived_identifier,
    parse_primary_location,
    short_openalex_id,
    url_identifiers,
)


class TestOpenalexIdConversion:
    def test_short_from_url(self):
        assert short_openalex_id("https://openalex.org/S20400310") == "S20400310"

    def test_short_already_short(self):
        assert short_openalex_id("S20400310") == "S20400310"

    def test_full_from_short(self):
        assert full_openalex_id("S20400310") == "https://openalex.org/S20400310"

    def test_full_already_url(self):
        assert (
            full_openalex_id("https://openalex.org/S20400310") == "https://openalex.org/S20400310"
        )


def _url_ids(urls):
    identifiers, _ = normalize_identifiers(url_identifiers(urls))
    assert all(i.role is SourceIdentifierRole.SECONDARY for i in identifiers)
    return [(str(i.id_type), i.value) for i in identifiers]


class TestUrlIdentifiers:
    def test_hal(self):
        assert _url_ids(["https://hal.science/hal-04123456v2"]) == [("hal_id", "hal-04123456")]

    def test_nnt(self):
        assert _url_ids(["https://www.theses.fr/2021CLFAC030"]) == [("nnt", "2021CLFAC030")]

    def test_pmid(self):
        assert _url_ids(["https://pubmed.ncbi.nlm.nih.gov/12345678"]) == [("pmid", "12345678")]

    def test_pmc_with_prefix(self):
        urls = ["https://www.ncbi.nlm.nih.gov/pmc/articles/PMC987654"]
        assert _url_ids(urls) == [("pmcid", "PMC987654")]

    def test_pmc_without_prefix(self):
        """Le préfixe PMC est ajouté même si l'URL ne le contient pas."""
        urls = ["https://www.ncbi.nlm.nih.gov/pmc/articles/987654"]
        assert _url_ids(urls) == [("pmcid", "PMC987654")]

    def test_arxiv(self):
        assert _url_ids(["http://arxiv.org/abs/1210.6893"]) == [("arxiv_id", "1210.6893")]

    def test_collecte_chaque_identifiant_distinct_dans_l_ordre(self):
        """Une version HAL ne fait pas un dépôt distinct."""
        urls = [
            "https://hal.science/hal-04111111",
            "https://pubmed.ncbi.nlm.nih.gov/12345678",
            "https://hal.science/hal-04222222",
            "https://hal.science/hal-04111111v2",
            "https://pubmed.ncbi.nlm.nih.gov/87654321",
        ]
        assert _url_ids(urls) == [
            ("hal_id", "hal-04111111"),
            ("pmid", "12345678"),
            ("hal_id", "hal-04222222"),
            ("pmid", "87654321"),
        ]

    def test_no_match_returns_empty(self):
        assert _url_ids(["https://example.com/foo", "https://random.org/bar"]) == []

    def test_empty_input(self):
        assert url_identifiers([]) == []


def _loc(**kwargs) -> OpenalexLocation:
    """Helper : OpenalexLocation avec tous les champs à None par défaut."""
    defaults = {
        "location_id": None,
        "landing_page_url": None,
        "source_id": None,
        "source_type": None,
        "source_display_name": None,
        "source_homepage_url": None,
    }
    defaults.update(kwargs)
    return OpenalexLocation(**defaults)


class TestMapOpenalexOaStatus:
    def test_known_statuses_passthrough(self):
        for raw in ("gold", "diamond", "hybrid", "bronze", "green", "closed"):
            assert map_openalex_oa_status(raw) == raw

    def test_none_returns_none(self):
        # OpenAlex ne s'est pas prononcé → délégation aux autres sources
        assert map_openalex_oa_status(None) is None

    def test_empty_string_returns_none(self):
        assert map_openalex_oa_status("") is None

    def test_unknown_value_returns_unknown(self):
        assert map_openalex_oa_status("some_new_label") == "unknown"
        assert map_openalex_oa_status("Gold") == "unknown", (
            "matching strict casse — OpenAlex utilise lowercase"
        )


class TestParsePrimaryLocation:
    def test_full_location(self):
        work = {
            "primary_location": {
                "id": "pmh:2023UCFAC123",
                "landing_page_url": "https://theses.fr/2023UCFAC123",
                "source": {
                    "id": "https://openalex.org/S4306400194",
                    "type": "repository",
                    "display_name": "theses.fr",
                    "homepage_url": "https://theses.fr",
                },
            }
        }
        loc = parse_primary_location(work)
        assert loc is not None
        assert loc.location_id == "pmh:2023UCFAC123"
        assert loc.landing_page_url == "https://theses.fr/2023UCFAC123"
        assert loc.source_id == "https://openalex.org/S4306400194"
        assert loc.source_type == "repository"
        assert loc.source_display_name == "theses.fr"
        assert loc.source_homepage_url == "https://theses.fr"

    def test_missing_primary(self):
        assert parse_primary_location({}) is None
        assert parse_primary_location({"primary_location": None}) is None

    def test_partial_location(self):
        work = {"primary_location": {"landing_page_url": "https://example.com"}}
        loc = parse_primary_location(work)
        assert loc is not None
        assert loc.landing_page_url == "https://example.com"
        assert loc.source_type is None


class TestIsThesesFrLocation:
    def test_via_display_name(self):
        assert is_theses_fr_location(_loc(source_display_name="theses.fr"))
        assert is_theses_fr_location(_loc(source_display_name="Theses.fr"))

    def test_via_landing_page_url(self):
        assert is_theses_fr_location(_loc(landing_page_url="https://www.theses.fr/2023UCFAC123"))

    def test_negative(self):
        assert not is_theses_fr_location(_loc(source_display_name="HAL"))
        assert not is_theses_fr_location(_loc())

    def test_domain_outside_the_host(self):
        """`theses.fr/` placé dans le chemin ne fait pas de la location une thèse."""
        assert not is_theses_fr_location(
            _loc(landing_page_url="https://exemple.fr/miroir/theses.fr/2023UCFAC123")
        )


class TestIsRepositoryLocation:
    def test_repository(self):
        assert is_repository_location(_loc(source_type="repository"))

    def test_serial(self):
        assert not is_repository_location(_loc(source_type="journal"))

    def test_none(self):
        assert not is_repository_location(_loc())


class TestIsHalLocation:
    def test_via_landing_page(self):
        # Landing page reconnue par le détecteur central : hôte HAL + docid à 8 chiffres, toute collection.
        assert is_hal_location(_loc(landing_page_url="https://hal.science/hal-04123456"))
        assert is_hal_location(
            _loc(landing_page_url="https://tel.archives-ouvertes.fr/tel-09876543")
        )
        assert is_hal_location(_loc(landing_page_url="https://dumas.ccsd.cnrs.fr/dumas-01234567"))

    def test_via_source_homepage(self):
        assert is_hal_location(
            _loc(source_type="repository", source_homepage_url="https://hal.science")
        )
        assert is_hal_location(
            _loc(source_type="repository", source_homepage_url="https://hal.inrae.fr")
        )
        assert is_hal_location(
            _loc(source_type="repository", source_homepage_url="https://tel.archives-ouvertes.fr")
        )

    def test_homepage_whose_host_is_not_a_hal_portal(self):
        """Le label `hal` ailleurs que dans l'hôte ne désigne pas un portail."""
        assert not is_hal_location(
            _loc(source_type="repository", source_homepage_url="https://exemple.fr/halle")
        )

    def test_via_source_display_name(self):
        assert is_hal_location(
            _loc(source_type="repository", source_display_name="HAL Archive ouverte")
        )

    def test_repository_without_hal_signal(self):
        # Repository qui n'est pas HAL (Zenodo, SPIRE…) → False
        assert not is_hal_location(_loc(source_type="repository", source_display_name="Zenodo"))

    def test_serial(self):
        assert not is_hal_location(_loc(source_type="journal", source_display_name="Nature"))

    def test_none(self):
        assert not is_hal_location(_loc())


class TestNamesPublisher:
    def test_hal(self):
        assert not names_publisher(_loc(landing_page_url="https://hal.science/hal-04123456"))

    def test_theses_fr(self):
        assert not names_publisher(_loc(source_display_name="theses.fr"))

    def test_repository(self):
        assert not names_publisher(_loc(source_type="repository"))

    def test_ebook_platform(self):
        assert names_publisher(_loc(source_type="ebook platform"))

    def test_serial(self):
        assert names_publisher(_loc(source_type="journal", source_display_name="Nature"))

    def test_none(self):
        assert names_publisher(None)


class TestNamesSerial:
    def test_repository(self):
        assert not names_serial(_loc(source_type="repository"))

    def test_ebook_platform(self):
        assert not names_serial(_loc(source_type="ebook platform"))

    def test_serial(self):
        assert names_serial(_loc(source_type="journal", source_display_name="Nature"))

    def test_none(self):
        assert names_serial(None)


class TestExtractNntFromLocation:
    def test_via_pmh_id(self):
        assert extract_nnt_from_location(_loc(location_id="pmh:2023UCFAC123")) == "2023UCFAC123"

    def test_via_landing_page_url(self):
        assert (
            extract_nnt_from_location(
                _loc(landing_page_url="http://www.theses.fr/2023UCFAC123/document")
            )
            == "2023UCFAC123"
        )

    def test_pmh_id_takes_precedence(self):
        # Si les deux sont présents, pmh: gagne
        loc = _loc(
            location_id="pmh:2023UCFAC123",
            landing_page_url="https://theses.fr/2024OTHERNNT",
        )
        assert extract_nnt_from_location(loc) == "2023UCFAC123"

    def test_no_match(self):
        assert extract_nnt_from_location(_loc()) is None
        assert extract_nnt_from_location(_loc(location_id="oai:HAL:hal-1")) is None
        assert extract_nnt_from_location(_loc(landing_page_url="https://example.com/")) is None

    def test_pmh_wrapping_an_oai_id_is_not_a_nnt(self):
        # Cas réel : un dépôt HAL moissonné en OAI-PMH a un location.id
        # « pmh:oai:HAL:hal-04677016v1 ». Les deux-points cassent le motif
        # alphanumérique → pas de NNT (sinon lien theses.fr mort sur la fiche).
        assert extract_nnt_from_location(_loc(location_id="pmh:oai:HAL:hal-04677016v1")) is None


class TestAuthorsMayBeTruncated:
    def test_cap_reached(self):
        assert authors_may_be_truncated({"authorships": [{}] * BULK_AUTHORSHIPS_CAP})

    def test_under_cap(self):
        assert not authors_may_be_truncated({"authorships": [{}] * 3})

    def test_without_authorships(self):
        assert not authors_may_be_truncated({})


class TestOpenalexDerivedIdentifier:
    def test_sans_localisation_principale(self):
        assert openalex_derived_identifier(None) is None

    def test_nnt_d_une_localisation_theses_fr(self):
        loc = _loc(source_display_name="theses.fr", location_id="pmh:2023UCFAC123")
        assert openalex_derived_identifier(loc) == SourceIdentifier(
            SourceIdentifierType.NNT, "2023UCFAC123", SourceIdentifierRole.DERIVED
        )

    def test_hal_id_d_une_localisation_hal(self):
        loc = _loc(landing_page_url="https://hal.science/hal-04123456v1")
        assert openalex_derived_identifier(loc) == SourceIdentifier(
            SourceIdentifierType.HAL_ID, "hal-04123456", SourceIdentifierRole.DERIVED
        )

    def test_doi_d_une_localisation_editeur(self):
        loc = _loc(landing_page_url="https://doi.org/10.1234/ABC", location_id="doi:10.1234/abc")
        assert openalex_derived_identifier(loc) == SourceIdentifier(
            SourceIdentifierType.DOI, "10.1234/abc", SourceIdentifierRole.DERIVED
        )

    def test_page_sans_identifiant(self):
        assert openalex_derived_identifier(_loc(landing_page_url="https://example.com/x")) is None
