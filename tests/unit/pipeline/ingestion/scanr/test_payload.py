from pipeline.ingestion.scanr.payload import (
    derive_scanr_oa_status,
    extract_nnt_from_scanr_id,
    select_leaf_affiliations,
)


class TestSelectLeafAffiliations:
    def test_filters_to_labo(self):
        """Seule l'affiliation à un laboratoire (champ `id_name_author_labo`) est conservée ; les tutelles sont écartées."""
        labo = {"name": "IHRIM blob", "id_name_author_labo": "idref###X###RNSR###IHRIM"}
        tutelle = {"name": "ENS Lyon, ..."}
        assert select_leaf_affiliations([labo, tutelle]) == [labo]

    def test_falls_back_when_none_marked(self):
        a = {"name": "Org A"}
        b = {"name": "Org B"}
        assert select_leaf_affiliations([a, b]) == [a, b]

    def test_empty(self):
        assert select_leaf_affiliations([]) == []


class TestExtractNntFromScanrId:
    def test_none_returns_none(self):
        assert extract_nnt_from_scanr_id(None) is None

    def test_empty_returns_none(self):
        assert extract_nnt_from_scanr_id("") is None

    def test_thesis_prefix_extracts_uppercase_nnt(self):
        assert extract_nnt_from_scanr_id("these2021CLFAC030") == "2021CLFAC030"

    def test_thesis_prefix_uppercases_nnt(self):
        assert extract_nnt_from_scanr_id("these2021clfac030") == "2021CLFAC030"

    def test_nnt_prefix_extracts_uppercase_nnt(self):
        assert extract_nnt_from_scanr_id("nnt2019clfad020") == "2019CLFAD020"

    def test_thesis_in_preparation_has_no_nnt(self):
        assert extract_nnt_from_scanr_id("nnts104391") is None

    def test_other_prefix_returns_none(self):
        assert extract_nnt_from_scanr_id("hal2021abcd") is None
        assert extract_nnt_from_scanr_id("doi:10.1234/foo") is None

    def test_uppercase_prefix_does_not_match(self):
        # ScanR écrit le préfixe en minuscules : un préfixe en majuscules ne désigne aucune thèse.
        assert extract_nnt_from_scanr_id("THESE2021CLFAC030") is None


class TestDeriveScanrOaStatus:
    def test_is_oa_none_returns_none(self):
        assert derive_scanr_oa_status(None, None) is None
        assert derive_scanr_oa_status(None, {"hostType": "repository"}) is None

    def test_is_oa_false_returns_closed(self):
        assert derive_scanr_oa_status(False, None) == "closed"
        assert derive_scanr_oa_status(False, {"hostType": "publisher"}) == "closed"

    def test_repository_returns_green(self):
        assert derive_scanr_oa_status(True, {"hostType": "repository"}) == "green"

    def test_publisher_with_cc_license_returns_hybrid(self):
        assert (
            derive_scanr_oa_status(True, {"hostType": "publisher", "license": "cc-by"}) == "hybrid"
        )
        assert (
            derive_scanr_oa_status(True, {"hostType": "publisher", "license": "cc-by-nc-nd"})
            == "hybrid"
        )
        assert (
            derive_scanr_oa_status(True, {"hostType": "publisher", "license": "CC-BY"}) == "hybrid"
        ), "license matching insensible à la casse"

    def test_publisher_without_cc_license_returns_bronze(self):
        assert derive_scanr_oa_status(True, {"hostType": "publisher", "license": ""}) == "bronze"
        assert (
            derive_scanr_oa_status(True, {"hostType": "publisher", "license": "other-oa"})
            == "bronze"
        )
        assert derive_scanr_oa_status(True, {"hostType": "publisher"}) == "bronze", (
            "license absente → bronze"
        )

    def test_unknown_or_missing_host_type_returns_none(self):
        assert derive_scanr_oa_status(True, None) is None
        assert derive_scanr_oa_status(True, {}) is None
        assert derive_scanr_oa_status(True, {"hostType": "unknown"}) is None
