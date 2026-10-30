"""Écriture d'un paramètre applicatif, et sa trace d'audit.

La table `config` contient les réglages d'exploitation du pipeline : années couvertes, périmètres retenus par phase, types de structure affichés. Les modifier change le comportement de l'application sans changer les données : seul l'événement d'audit en garde la trace.

L'événement contient seulement la valeur écrite. La valeur antérieure est dans l'événement qui l'a posée.
"""

import pytest

from tests.integration.helpers.db import owner_pool
from tests.integration.helpers.seeds import seed_config

_CLE = "test_audit_config_key"


@pytest.fixture
def cle_posee(client):
    """Paramètre existant : la route refuse une clé inconnue."""
    seed_config(_CLE, "avant")
    yield _CLE
    with owner_pool() as cur:
        cur.execute("DELETE FROM config WHERE key = %s", (_CLE,))
        cur.execute("DELETE FROM audit_log WHERE event_type = 'config.updated'")


class TestTracabilite:
    def test_la_modification_d_un_parametre_est_consignee(self, auth_client, cle_posee):
        r = auth_client.put(f"/api/config/{cle_posee}", json={"value": "apres"})
        assert r.status_code == 200, r.text

        with owner_pool() as cur:
            cur.execute(
                "SELECT aggregate_type, aggregate_id, payload, user_id FROM audit_log "
                "WHERE event_type = 'config.updated' ORDER BY id"
            )
            evenements = cur.fetchall()

        assert len(evenements) == 1
        evenement = evenements[0]
        assert evenement["aggregate_type"] == "config"
        # La clé est un texte et l'identifiant d'entité (`aggregate_id`) un entier : la clé est dans la charge utile.
        assert evenement["aggregate_id"] is None
        assert evenement["payload"] == {"key": cle_posee, "value": "apres"}
        assert evenement["user_id"]

    def test_une_cle_inconnue_ne_laisse_aucune_trace(self, auth_client):
        r = auth_client.put("/api/config/cle-qui-n-existe-pas", json={"value": "x"})
        assert r.status_code == 404

        with owner_pool() as cur:
            cur.execute("SELECT count(*) AS n FROM audit_log WHERE event_type = 'config.updated'")
            assert cur.fetchone()["n"] == 0
