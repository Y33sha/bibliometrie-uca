"""En-têtes de sécurité posés sur toute réponse par le middleware, et ordre de la pile."""


class TestSecurityHeaders:
    def test_headers_present_on_response(self, client):
        r = client.get("/api/auth/check")
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "strict-origin-when-cross-origin"

    def test_les_capteurs_du_navigateur_sont_refuses(self, client):
        """Aucune page n'en demande : les refuser ferme la porte à du code qui s'exécuterait dans la page."""
        politique = client.get("/api/auth/check").headers["permissions-policy"]
        for capacite in ("geolocation", "camera", "microphone", "payment", "usb"):
            assert f"{capacite}=()" in politique

    def test_le_contexte_de_navigation_est_isole(self, client):
        """Une page ouverte depuis l'application perd la référence vers celle qui l'a ouverte, sans dépendre de `rel="noopener"` lien par lien."""
        r = client.get("/api/auth/check")
        assert r.headers["cross-origin-opener-policy"] == "same-origin"

    def test_les_ressources_ne_se_chargent_pas_depuis_un_autre_site(self, client):
        """Une requête sans CORS venue d'une origine tierce n'obtient rien : le pendant, pour les ressources, de l'isolement du contexte de navigation."""
        r = client.get("/api/auth/check")
        assert r.headers["cross-origin-resource-policy"] == "same-origin"

    def test_les_en_tetes_couvrent_aussi_l_interface(self, client):
        """Le middleware les pose sur toute réponse, pages du frontend comprises.

        L'attendu est lu dans le middleware lui-même : un en-tête qu'on y ajoute est couvert sans qu'on y pense, et un en-tête qu'on en retire cesse d'être exigé ici.
        """
        from interfaces.api.app import _SECURITY_HEADERS

        entetes = client.get("/").headers
        for nom, valeur in _SECURITY_HEADERS.items():
            assert entetes[nom.lower()] == valeur, nom


class TestPolitiqueDeSecuriteDeContenu:
    """Politique de sécurité de contenu posée en en-tête, en regard de celle que les pages du frontend portent en balise.

    Une balise `<meta>` ne peut pas exprimer `frame-ancestors` : la directive n'a d'effet qu'en en-tête, et c'est la formulation dont `X-Frame-Options` est l'ancêtre. Les réponses de l'API, qui ne rendent que du JSON, portent en plus une politique qui n'autorise aucune ressource.
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
        """Les pages portent leur propre politique en balise, qui autorise nommément les scripts de l'application : celle de l'en-tête ne doit pas la contredire."""
        politique = client.get("/").headers["content-security-policy"]
        assert politique == "frame-ancestors 'none'"

    def test_un_refus_la_porte_aussi(self, client):
        r = client.post("/api/perimeters", json={})
        assert r.status_code == 401
        assert "default-src 'none'" in r.headers["content-security-policy"]


class TestMiseEnCache:
    """Aucun cache du chemin ne garde une réponse de l'API.

    Une même adresse ne rend pas toujours le même corps : la configuration se restreint à une liste blanche de clés sans session et s'ouvre avec. Un cache partagé qui rangerait la variante servie à une session ouverte la rendrait ensuite à un appelant anonyme.
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
        """Les fichiers du frontend portent leur empreinte dans leur nom : les mettre en cache est ce qui rend une page rapide au second chargement."""
        r = client.get("/")
        assert r.headers.get("cache-control") != "no-store"


class TestOrdreDeLaPile:
    """Le middleware CORS enveloppe les autres, et voit donc les réponses qu'ils composent.

    Un refus dépourvu d'en-têtes CORS arrive au navigateur d'une origine autorisée comme une erreur CORS opaque : le code et le message de refus sont perdus, et la page ne peut rien en dire. Or les middlewares d'authentification, de plafond et de pagination composent leurs refus eux-mêmes, sans laisser passer la requête — d'où l'ordre.

    L'ordre est vérifié sur la pile plutôt que sur une réponse : les origines autorisées se figent à la construction du middleware, si bien qu'un appel n'en montre les en-têtes que sur un déploiement qui en énumère, et la production n'en énumère aucune.
    """

    def test_cors_enveloppe_les_autres_middlewares(self):
        from fastapi.middleware.cors import CORSMiddleware

        from interfaces.api.app import app

        # Starlette range la pile du plus extérieur au plus intérieur.
        assert app.user_middleware[0].cls is CORSMiddleware
