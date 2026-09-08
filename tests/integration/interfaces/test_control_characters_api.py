"""Un paramètre texte portant un caractère de contrôle est refusé par le contrat de la route.

PostgreSQL n'accepte l'octet NUL dans aucun champ texte, et le driver écarte la valeur à l'adaptation des paramètres. Sans refus en amont, la valeur traverse la route et rompt au moment de la requête, en 500. Les chemins couverts ici sont ceux qu'une analyse de sécurité a fait tomber.
"""

import pytest

_CHEMINS = [
    ("/api/authorships/orphans", {"page": 1, "per_page": 50, "search": "\x00"}),
    ("/api/feedback/false-negatives", {"structure_id": 10, "search": "\x00"}),
    ("/api/feedback/false-positives", {"structure_id": 10, "search": "\x00"}),
    ("/api/persons/10/name-form-authorships", {"name_form": "\x00"}),
    ("/api/subjects", {"page": 1, "per_page": 50, "search": "\x00", "min_count": 1}),
]


@pytest.mark.parametrize(("chemin", "params"), _CHEMINS)
def test_un_octet_nul_est_refuse(client, chemin, params):
    assert client.get(chemin, params=params).status_code == 422


@pytest.mark.parametrize("caractere", ["\x00", "\x07", "\x1b", "\x7f"])
def test_les_autres_caracteres_de_controle_sont_refuses(client, caractere):
    assert client.get("/api/publications", params={"search": caractere}).status_code == 422


@pytest.mark.parametrize("caractere", ["\t", "\r", "\n"])
def test_les_separateurs_recopies_depuis_un_document_passent(client, caractere):
    assert client.get("/api/publications", params={"search": caractere}).status_code == 200
