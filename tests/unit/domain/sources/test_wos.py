from domain.sources.wos import derive_wos_api_oa_status, is_wos_author_exploitable


class TestIsWosAuthorExploitable:
    def test_full_name_and_daisng_id_present(self):
        assert is_wos_author_exploitable({"full_name": "Dupont, Jean", "daisng_id": "12345"})

    def test_missing_daisng_id(self):
        assert not is_wos_author_exploitable({"full_name": "Dupont, Jean"})
        assert not is_wos_author_exploitable({"full_name": "Dupont, Jean", "daisng_id": None})
        assert not is_wos_author_exploitable({"full_name": "Dupont, Jean", "daisng_id": ""})

    def test_missing_full_name(self):
        assert not is_wos_author_exploitable({"daisng_id": "12345"})
        assert not is_wos_author_exploitable({"daisng_id": "12345", "full_name": None})
        assert not is_wos_author_exploitable({"daisng_id": "12345", "full_name": ""})

    def test_empty_dict(self):
        assert not is_wos_author_exploitable({})


class TestDeriveWosApiOaStatus:
    def test_y_returns_gold(self):
        assert derive_wos_api_oa_status("Y") == "gold"

    def test_n_returns_none(self):
        # 'N' WoS ne signifie pas closed (WoS ne connaît pas vraiment
        # la voie OA), on délègue
        assert derive_wos_api_oa_status("N") is None

    def test_none_returns_none(self):
        assert derive_wos_api_oa_status(None) is None

    def test_empty_returns_none(self):
        assert derive_wos_api_oa_status("") is None

    def test_unknown_value_returns_none(self):
        assert derive_wos_api_oa_status("yes") is None
        assert derive_wos_api_oa_status("y") is None, "match strict casse"
