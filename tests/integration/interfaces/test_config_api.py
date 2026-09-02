"""Écriture d'un paramètre applicatif, et sa trace.

La table `config` porte les réglages d'exploitation du pipeline : années couvertes, périmètres retenus par phase, types de structure affichés. En modifier un change le comportement de l'application sans rien changer aux données — un tel changement ne se relit donc nulle part ensuite, d'où l'événement d'audit.

La valeur antérieure n'est pas consignée : le journal la porte déjà, sous la forme de l'événement qui l'a posée.
"""

import os
from contextlib import contextmanager

import psycopg
import pytest
from psycopg.rows import dict_row

_DB_ARGS = {
    "dbname": "bibliometrie_test",
    "user": os.environ["DB_OWNER_USER"],
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "5432")),
}
if os.environ.get("DB_OWNER_PASSWORD"):
    _DB_ARGS["password"] = os.environ["DB_OWNER_PASSWORD"]

_CLE = "test_audit_config_key"


@contextmanager
def _pool():
    conn = psycopg.connect(**_DB_ARGS, row_factory=dict_row)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


@pytest.fixture
def cle_posee(client):
    """Un paramètre existant : la route refuse une clé inconnue, qu'elle ne crée pas."""
    with _pool() as cur:
        cur.execute(
            "INSERT INTO config (key, value) VALUES (%s, to_jsonb('avant'::text)) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (_CLE,),
        )
    yield _CLE
    with _pool() as cur:
        cur.execute("DELETE FROM config WHERE key = %s", (_CLE,))
        cur.execute("DELETE FROM audit_log WHERE event_type = 'config.updated'")


class TestTracabilite:
    def test_la_modification_d_un_parametre_est_consignee(self, auth_client, cle_posee):
        r = auth_client.put(f"/api/config/{cle_posee}", json={"value": "apres"})
        assert r.status_code == 200, r.text

        with _pool() as cur:
            cur.execute(
                "SELECT aggregate_type, aggregate_id, payload, user_id FROM audit_log "
                "WHERE event_type = 'config.updated' ORDER BY id"
            )
            evenements = cur.fetchall()

        assert len(evenements) == 1
        evenement = evenements[0]
        assert evenement["aggregate_type"] == "config"
        # La clé est un texte, là où l'identifiant d'agrégat est un entier : elle vit dans la
        # charge utile.
        assert evenement["aggregate_id"] is None
        assert evenement["payload"] == {"key": cle_posee, "value": "apres"}
        assert evenement["user_id"]

    def test_une_cle_inconnue_ne_laisse_aucune_trace(self, auth_client):
        r = auth_client.put("/api/config/cle-qui-n-existe-pas", json={"value": "x"})
        assert r.status_code == 404

        with _pool() as cur:
            cur.execute("SELECT count(*) AS n FROM audit_log WHERE event_type = 'config.updated'")
            assert cur.fetchone()["n"] == 0
