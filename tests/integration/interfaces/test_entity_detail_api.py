"""Routes de détail sur un identifiant sans entité : redirection vers l'entité conservée par une fusion, sinon 404."""

import pytest

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import seed_serial

_ABSORBED_ID = 999999990


def _redirect(entity: str, absorbed_id: int, kept_id: int) -> None:
    with owner_pool() as cur:
        cur.execute(
            "INSERT INTO merge_redirects (entity, absorbed_id, kept_id) "
            "VALUES (CAST(%s AS merged_entity), %s, %s)",
            (entity, absorbed_id, kept_id),
        )


def test_absorbed_id_redirects_to_kept_with_query_string(client):
    kept = seed_serial()
    _redirect("serial", _ABSORBED_ID, kept)

    r = client.get(f"/api/serials/{_ABSORBED_ID}?tab=dashboard", follow_redirects=False)

    assert r.status_code == 308
    assert r.headers["location"] == f"{client.app.root_path}/api/serials/{kept}?tab=dashboard"
    assert client.get(f"/api/serials/{_ABSORBED_ID}").json()["id"] == kept


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/api/persons/999999999", "Personne introuvable"),
        ("/api/serials/999999999", "Revue introuvable"),
        ("/api/publishers/999999999", "Éditeur introuvable"),
        ("/api/monographs/999999999", "Monographie introuvable"),
        ("/api/publications/999999999", "Publication introuvable"),
    ],
)
def test_unknown_id_without_redirect_is_not_found(client, path, message):
    r = client.get(path)
    assert r.status_code == 404
    assert r.json() == {"detail": message}
