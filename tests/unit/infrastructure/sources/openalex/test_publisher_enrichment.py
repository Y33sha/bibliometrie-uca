"""Adapter OpenAlex Publishers → enrichissement du pays des éditeurs : extraction et fetch batch."""

from infrastructure.sources.openalex import publisher_enrichment as mod


class TestExtractCountry:
    def test_premier_code_en_minuscule(self):
        assert mod.extract_country({"id": "P1", "country_codes": ["FR", "DE"]}) == "fr"

    def test_none_quand_la_liste_est_vide(self):
        assert mod.extract_country({"id": "P1", "country_codes": []}) is None

    def test_none_quand_le_champ_est_absent(self):
        assert mod.extract_country({"id": "P1"}) is None


class TestFetchPublishersBatch:
    def _payload(self, *publishers):
        return {"results": list(publishers)}

    def test_associe_identifiant_court_et_pays(self, monkeypatch):
        payload = self._payload(
            {"id": "https://openalex.org/P1", "country_codes": ["NL"]},
            {"id": "https://openalex.org/P2", "country_codes": []},
        )
        monkeypatch.setattr(mod, "http_request_with_retry", lambda *a, **k: payload)
        out = mod.fetch_publishers_batch(
            ["P1", "P2"], openalex_publishers_api="x", api_key=None, mailto="m"
        )
        assert out == {"P1": "nl", "P2": None}

    def test_un_editeur_absent_de_la_reponse_reste_absent(self, monkeypatch):
        """`None` dit « la source ne connaît pas de pays » ; l'absence de clé dit « la source n'a rien répondu ». L'orchestrateur distingue les deux."""
        payload = self._payload({"id": "https://openalex.org/P1", "country_codes": ["FR"]})
        monkeypatch.setattr(mod, "http_request_with_retry", lambda *a, **k: payload)
        out = mod.fetch_publishers_batch(
            ["P1", "P2"], openalex_publishers_api="x", api_key=None, mailto="m"
        )
        assert out == {"P1": "fr"}

    def test_dictionnaire_vide_sur_echec(self, monkeypatch):
        """L'échec est déjà compté au circuit-breaker par le helper HTTP : l'adapter rend un lot vide, l'orchestrateur consulte le breaker."""

        def boom(*_a, **_k):
            raise RuntimeError("network down")

        monkeypatch.setattr(mod, "http_request_with_retry", boom)
        out = mod.fetch_publishers_batch(
            ["P1"], openalex_publishers_api="x", api_key=None, mailto="m"
        )
        assert out == {}

    def test_la_cle_d_api_prime_sur_l_adresse_polite_pool(self, monkeypatch):
        captured: dict = {}

        def capture(*_a, **kwargs):
            captured.update(kwargs["params"])
            return {"results": []}

        monkeypatch.setattr(mod, "http_request_with_retry", capture)
        mod.fetch_publishers_batch(
            ["P1"], openalex_publishers_api="x", api_key="cle", mailto="m@example.org"
        )
        assert captured["api_key"] == "cle"
        assert "mailto" not in captured
