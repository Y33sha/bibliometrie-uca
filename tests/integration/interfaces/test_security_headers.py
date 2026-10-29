"""En-têtes de sécurité posés sur toute réponse par le middleware, et ordre de la pile."""


class TestSecurityHeaders:
    def test_headers_present_on_response(self, client):
        r = client.get("/api/auth/check")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_les_capteurs_du_navigateur_sont_refuses(self, client):
        """Aucune page n'utilise ces capacités : les refuser en prive un code injecté dans la page."""
        politique = client.get("/api/auth/check").headers["permissions-policy"]
        for capacite in ("geolocation", "camera", "microphone", "payment", "usb"):
            assert f"{capacite}=()" in politique

    def test_le_contexte_de_navigation_est_isole(self, client):
        """Une page ouverte depuis l'application perd la référence vers celle qui l'a ouverte, sans dépendre de `rel="noopener"` lien par lien."""
        r = client.get("/api/auth/check")
        assert r.headers["cross-origin-opener-policy"] == "same-origin"

    def test_les_ressources_ne_se_chargent_pas_depuis_un_autre_site(self, client):
        """Une requête sans CORS venue d'une autre origine n'obtient pas la ressource."""
        r = client.get("/api/auth/check")
        assert r.headers["cross-origin-resource-policy"] == "same-origin"

    def test_les_en_tetes_couvrent_aussi_l_interface(self, client):
        """Le middleware pose les en-têtes sur toute réponse, pages du frontend comprises.

        L'attendu est lu dans le middleware : le test suit tout en-tête qu'on y ajoute ou qu'on en retire.
        """
        from interfaces.api.app import _SECURITY_HEADERS

        entetes = client.get("/").headers
        for nom, valeur in _SECURITY_HEADERS.items():
            assert entetes[nom.lower()] == valeur, nom


class TestPolitiqueDeSecuriteDeContenu:
    """Politique de sécurité de contenu en en-tête, à côté de celle que les pages du frontend déclarent en balise.

    La directive `frame-ancestors` agit seulement en en-tête. Les réponses de l'API, en JSON, ont en plus une politique qui n'autorise aucune ressource.
    """

    def test_toute_reponse_refuse_l_insertion_dans_un_cadre(self, client):
        for chemin in ("/", "/api/auth/check"):
            politique = client.get(chemin).headers["content-security-policy"]
            assert "frame-ancestors 'none'" in politique, chemin

    def test_une_reponse_d_api_n_autorise_aucune_ressource(self, client):
        politique = client.get("/api/config").headers["content-security-policy"]
        for directive in ("default-src 'none'", "base-uri 'none'", "form-action 'none'"):
            assert directive in politique

    def test_la_politique_de_l_interface_ne_restreint_que_le_cadre(self, client):
        """Les pages déclarent en balise leur propre politique, qui autorise les scripts de l'application : l'en-tête se limite à `frame-ancestors`."""
        politique = client.get("/").headers["content-security-policy"]
        assert politique == "frame-ancestors 'none'"

    def test_un_refus_la_porte_aussi(self, client):
        r = client.post("/api/perimeters", json={})
        assert r.status_code == 401
        assert "default-src 'none'" in r.headers["content-security-policy"]


class TestMiseEnCache:
    """Aucun cache intermédiaire ne garde une réponse de l'API.

    Une même adresse renvoie des corps différents selon la session : sans session, la configuration se limite à une liste blanche de clés. Un cache partagé rendrait à un appelant anonyme la variante servie à une session.
    """

    def test_une_lecture_d_api_interdit_la_mise_en_cache(self, client):
        assert client.get("/api/config").headers["cache-control"] == "no-store"

    def test_l_interdiction_couvre_la_surface_d_api(self, client):
        for chemin in ("/api/auth/check", "/api/publications", "/api/stats/summary"):
            r = client.get(chemin)
            assert r.headers.get("cache-control") == "no-store", chemin

    def test_un_refus_la_porte_aussi(self, client):
        """Le refus d'une écriture non authentifiée passe par le même middleware."""
        r = client.post("/api/perimeters", json={})
        assert r.status_code == 401
        assert r.headers.get("cache-control") == "no-store"

    def test_l_interface_garde_son_cache(self, client):
        """Les fichiers du frontend contiennent leur empreinte dans leur nom : leur mise en cache accélère le second chargement."""
        r = client.get("/")
        assert r.headers.get("cache-control") != "no-store"


class TestOrdreDeLaPile:
    """Le middleware CORS enveloppe ceux qui composent des réponses, et voit donc leurs refus. Seul le middleware du préfixe de déploiement, qui ne répond jamais, l'enveloppe à son tour.

    Un refus sans en-têtes CORS arrive au navigateur d'une origine autorisée comme une erreur CORS opaque : le code et le message sont perdus. Or les middlewares d'authentification, de plafond et de pagination composent leurs refus eux-mêmes.

    L'ordre est vérifié sur la pile : les origines autorisées sont fixées à la construction du middleware, et la production n'en déclare aucune, donc une réponse ne montre pas les en-têtes CORS.
    """

    def test_cors_enveloppe_les_autres_middlewares(self):
        from fastapi.middleware.cors import CORSMiddleware

        from interfaces.api.app import app
        from interfaces.api.route_path import RootPath

        # Starlette range la pile du plus extérieur au plus intérieur.
        assert [m.cls for m in app.user_middleware[:2]] == [RootPath, CORSMiddleware]
