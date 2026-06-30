from datetime import date

from domain.sources.hal import derive_hal_oa_status


class TestDeriveHalOaStatus:
    def test_file_main_present_returns_green(self):
        # Cas vrai dépôt HAL : fileMain_s pointe vers /document
        assert derive_hal_oa_status(True, "https://hal.science/hal-12345/document", None) == "green"

    def test_file_main_present_overrides_open_access_false(self):
        # Cas limite : fichier déposé même si openAccess_bool serait False
        # (ne devrait pas arriver mais on tranche en faveur du fichier)
        assert (
            derive_hal_oa_status(False, "https://hal.science/hal-12345/document", None) == "green"
        )

    def test_arxiv_link_returns_green(self):
        assert derive_hal_oa_status(True, None, "arxiv") == "green"

    def test_pubmedcentral_link_returns_green(self):
        assert derive_hal_oa_status(True, None, "pubmedcentral") == "green"

    def test_openaccess_link_returns_hybrid(self):
        # Lien éditeur sans signal de licence : hybrid par défaut conservatif
        # (cohérent avec ScanR publisher+cc-*). best_oa_status promeut à gold
        # si OpenAlex confirme un journal full-OA.
        assert derive_hal_oa_status(True, None, "openaccess") == "hybrid"

    def test_istex_link_delegated(self):
        # Plateforme abonnement, statut OA réel ambigu → on délègue
        assert derive_hal_oa_status(True, None, "istex") is None

    def test_open_access_false_no_signal_returns_closed(self):
        assert derive_hal_oa_status(False, None, None) == "closed"
        assert derive_hal_oa_status(False, "", None) == "closed"

    def test_open_access_true_no_signal_returns_none(self):
        # Cas openAccess=True mais ni file_main ni link_ext_id : on délègue
        assert derive_hal_oa_status(True, None, None) is None
        assert derive_hal_oa_status(True, "", None) is None

    def test_open_access_none_returns_none(self):
        assert derive_hal_oa_status(None, None, None) is None

    def test_file_main_with_embargo_returns_embargoed(self):
        # Fichier déposé mais sous embargo (date de levée renseignée) → embargoed, pas green.
        assert (
            derive_hal_oa_status(
                False, "https://hal.science/hal-12345/document", None, date(2027, 1, 1)
            )
            == "embargoed"
        )

    def test_file_main_without_embargo_stays_green(self):
        # Sans embargo (embargo_until=None) : comportement inchangé.
        assert (
            derive_hal_oa_status(True, "https://hal.science/hal-12345/document", None, None)
            == "green"
        )

    def test_embargo_without_file_main_not_embargoed(self):
        # Pas de fichier déposé : l'embargo seul ne tague pas (délégation).
        assert derive_hal_oa_status(True, None, None, date(2027, 1, 1)) is None
