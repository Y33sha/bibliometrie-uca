"""En-têtes de sécurité posés sur toute réponse par le middleware."""


class TestSecurityHeaders:
    def test_headers_present_on_response(self, client):
        r = client.get("/api/auth/check")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"
