from datetime import date

from pipeline.ingestion.hal.payload import (
    derive_hal_oa_status,
    extract_hal_source_extras,
    hal_text_field,
)


class TestHalTextField:
    def test_non_textual_first_value_is_rendered_as_text(self):
        assert hal_text_field([123, "suite"]) == "123"


class TestExtractHalMeta:
    def test_indicateur_actes_series_et_titre_de_source(self):
        doc = {
            "proceedings_s": "1",
            "serie_s": ["Occidens (3)", " ", "Occidens (3)"],
            "source_s": "Actes des 8èmes journées scientifiques",
        }
        assert extract_hal_source_extras(doc) == {
            "proceedings": True,
            "series": ["Occidens (3)"],
            "source_title": "Actes des 8èmes journées scientifiques",
        }

    def test_sans_actes(self):
        assert extract_hal_source_extras({"proceedings_s": "0"}) == {"proceedings": False}

    def test_licence_du_fichier_depose(self):
        doc = {"licence_s": "https://creativecommons.org/licenses/by/4.0/"}
        assert extract_hal_source_extras(doc) == {
            "licence": "https://creativecommons.org/licenses/by/4.0/"
        }

    def test_enregistrement_source_muet(self):
        assert extract_hal_source_extras({"title_s": ["Titre"]}) is None


class TestDeriveHalOaStatus:
    def test_file_main_present_returns_green(self):
        # Dépôt HAL avec fichier : fileMain_s pointe vers /document.
        assert derive_hal_oa_status(True, "https://hal.science/hal-12345/document", None) == "green"

    def test_file_main_present_overrides_open_access_false(self):
        # Un fichier déposé l'emporte sur openAccess_bool à False.
        assert (
            derive_hal_oa_status(False, "https://hal.science/hal-12345/document", None) == "green"
        )

    def test_arxiv_link_returns_green(self):
        assert derive_hal_oa_status(True, None, "arxiv") == "green"

    def test_pubmedcentral_link_returns_green(self):
        assert derive_hal_oa_status(True, None, "pubmedcentral") == "green"

    def test_openaccess_link_returns_hybrid(self):
        # Lien éditeur sans licence connue : hybrid par défaut.
        assert derive_hal_oa_status(True, None, "openaccess") == "hybrid"

    def test_istex_link_delegated(self):
        # Plateforme sur abonnement, statut ambigu : la décision revient aux autres sources.
        assert derive_hal_oa_status(True, None, "istex") is None

    def test_open_access_false_no_signal_returns_closed(self):
        assert derive_hal_oa_status(False, None, None) == "closed"
        assert derive_hal_oa_status(False, "", None) == "closed"

    def test_open_access_true_no_signal_returns_none(self):
        # openAccess à True sans fichier ni lien externe : la décision revient aux autres sources.
        assert derive_hal_oa_status(True, None, None) is None
        assert derive_hal_oa_status(True, "", None) is None

    def test_open_access_none_returns_none(self):
        assert derive_hal_oa_status(None, None, None) is None

    def test_file_main_with_embargo_returns_embargoed(self):
        # Fichier déposé sous embargo (date de levée renseignée) : embargoed.
        assert (
            derive_hal_oa_status(
                False, "https://hal.science/hal-12345/document", None, date(2027, 1, 1)
            )
            == "embargoed"
        )

    def test_file_main_without_embargo_stays_green(self):
        # Sans date d'embargo, le fichier déposé donne green.
        assert (
            derive_hal_oa_status(True, "https://hal.science/hal-12345/document", None, None)
            == "green"
        )

    def test_embargo_without_file_main_not_embargoed(self):
        # Sans fichier déposé, l'embargo seul ne donne aucun statut.
        assert derive_hal_oa_status(True, None, None, date(2027, 1, 1)) is None
