"""Un paramètre texte qui contient un caractère de contrôle est refusé en 422 par le contrat de la route ; tabulation et fins de ligne passent.

PostgreSQL refuse l'octet NUL dans tout champ texte, et le driver lève une exception à l'adaptation du paramètre. Sans refus en amont, la requête échoue en 500. Les chemins listés sont ceux qu'une analyse de sécurité a signalés.
"""

import pytest

_CHEMINS = [
    ("/api/contributions/orphans", {"page": 1, "per_page": 50, "search": "\x00"}),
    ("/api/feedback/false-negatives", {"structure_id": 10, "search": "\x00"}),
    ("/api/feedback/false-positives", {"structure_id": 10, "search": "\x00"}),
    ("/api/persons/10/name-form-contributions", {"name_form": "\x00"}),
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
