"""Helper de test : router des requêtes HTTP simulées au-dessus de `httpx.MockTransport`.

`MockTransport` répond à toute requête par une fonction unique. Ce module lui ajoute ce dont les tests ont besoin : des routes déclarées par méthode et URL, la réponse ou l'exception que chacune sert, et le compte des appels reçus.

Une route se déclare par une URL sans paramètres de requête ; les paramètres portés par la requête réelle — clés d'API, pagination, filtres — ne participent pas au filtrage. Le rapprochement porte donc sur la méthode, le schéma, l'hôte, le port et le chemin.

La fixture `http_mock` de `tests/conftest.py` installe le routeur sur les clients construits pendant le test, que le test les crée lui-même ou que le code appelé les crée pour son compte.
"""

from __future__ import annotations

from collections.abc import Sequence

import httpx

_Outcome = httpx.Response | Exception


def _target(url: httpx.URL) -> tuple[str, str, int | None, str]:
    """Partie de l'URL qui identifie une route."""
    return (url.scheme, url.host, url.port, url.path)


def _replay(response: httpx.Response) -> httpx.Response:
    """Copie d'une réponse, servie à la place de l'originale.

    Un flux lu ne se relit pas : sans copie, une route rejouée rendrait une réponse inutilisable au deuxième appel.
    """
    return httpx.Response(response.status_code, headers=response.headers, content=response.content)


class Route:
    """Réponses servies pour une méthode et une URL, et appels reçus."""

    def __init__(self, method: str, url: str) -> None:
        self.method = method.upper()
        self.target = _target(httpx.URL(url))
        self.calls: list[httpx.Request] = []
        self._queue: list[_Outcome] = []
        self._repeated: _Outcome | None = None

    def mock(
        self,
        *,
        return_value: httpx.Response | None = None,
        side_effect: Exception | Sequence[_Outcome] | None = None,
    ) -> Route:
        """Pose ce que la route sert : `return_value` à chaque appel, `side_effect` levée à chaque appel si c'est une exception, ou consommée dans l'ordre si c'est une suite."""
        if side_effect is None:
            self._repeated = return_value
        elif isinstance(side_effect, Exception):
            self._repeated = side_effect
        else:
            self._queue = list(side_effect)
        return self

    @property
    def called(self) -> bool:
        return bool(self.calls)

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def matches(self, request: httpx.Request) -> bool:
        return request.method == self.method and _target(request.url) == self.target

    def serve(self, request: httpx.Request) -> httpx.Response:
        """Enregistre l'appel, puis rend la réponse suivante ou lève l'exception posée."""
        self.calls.append(request)
        outcome = self._queue.pop(0) if self._queue else self._repeated
        if outcome is None:
            raise AssertionError(
                f"{self.method} {request.url} : la route n'a plus de réponse à servir."
            )
        if isinstance(outcome, Exception):
            raise outcome
        return _replay(outcome)


class HttpMock:
    """Routeur des requêtes simulées d'un test.

    Les routes sont essayées dans l'ordre de déclaration. Une requête qu'aucune ne réclame fait échouer le test, pour qu'un appel sortant imprévu ne passe pas pour un succès.
    """

    def __init__(self) -> None:
        self._routes: list[Route] = []
        self.transport = httpx.MockTransport(self._serve)

    def get(self, url: str) -> Route:
        return self._declare("GET", url)

    def post(self, url: str) -> Route:
        return self._declare("POST", url)

    def _declare(self, method: str, url: str) -> Route:
        route = Route(method, url)
        self._routes.append(route)
        return route

    def _serve(self, request: httpx.Request) -> httpx.Response:
        for route in self._routes:
            if route.matches(request):
                return route.serve(request)
        raise AssertionError(f"Requête non simulée : {request.method} {request.url}")
