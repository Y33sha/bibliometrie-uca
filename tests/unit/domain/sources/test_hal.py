from domain.sources.hal import derive_hal_doc_type, derive_hal_oa_status


class TestDeriveHalDocType:
    def test_combined_key_wins_when_mapped(self):
        # ART + ARTREV → review (clé combinée mappée)
        assert derive_hal_doc_type("ART", "ARTREV") == "review"
        # ART + DATAPAPER → data_paper
        assert derive_hal_doc_type("ART", "DATAPAPER") == "data_paper"
        # UNDEFINED + PREPRINT → preprint
        assert derive_hal_doc_type("UNDEFINED", "PREPRINT") == "preprint"

    def test_combined_key_falls_back_to_type_when_unmapped(self):
        # ART + INCONNU → fallback sur ART → article
        assert derive_hal_doc_type("ART", "INCONNU_SUBTYPE") == "article"

    def test_no_subtype_uses_type_directly(self):
        assert derive_hal_doc_type("ART", None) == "article"
        assert derive_hal_doc_type("ART", "") == "article"
        assert derive_hal_doc_type("THESE", None) == "thesis"

    def test_unknown_type_returns_other(self):
        assert derive_hal_doc_type("INCONNU", None) == "other"
        assert derive_hal_doc_type(None, None) == "other"

    def test_case_insensitive(self):
        # map_doc_type lowercase la clé en interne
        assert derive_hal_doc_type("art", "artrev") == "review"
        assert derive_hal_doc_type("Art", "ArtRev") == "review"


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
