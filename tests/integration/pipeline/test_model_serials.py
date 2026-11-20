"""Modèle open access des revues (`model_serials`) : DOAJ et Diamond Discovery Hub pour diamond, OpenAlex pour les autres."""

from sqlalchemy import text

from pipeline.transformation.publishing.serials.model_serials import model_serials
from tests.integration.helpers.serials import add_to_serial_list, insert_serial


def _serial(conn, title, *, oa_model=None, is_oa=None, manual=False, in_doaj=False, fees=None):
    """Insère une revue, son open access intégral d'après OpenAlex et, avec `fees` (APC, autres frais), sa fiche DOAJ."""
    serial_id = insert_serial(conn, title, oa_model=oa_model, is_in_doaj=in_doaj)
    conn.execute(
        text("""
            UPDATE serials SET openalex_is_oa = :is_oa,
                doaj_payload = CASE WHEN CAST(:apc AS text) IS NULL THEN NULL
                    ELSE jsonb_build_object('APC', CAST(:apc AS text), 'Has other fees', CAST(:other AS text)) END,
                manual_fields = CASE WHEN :manual THEN ARRAY['oa_model'] ELSE manual_fields END
            WHERE id = :id
        """),
        {
            "is_oa": is_oa,
            "apc": fees[0] if fees else None,
            "other": fees[1] if fees else None,
            "manual": manual,
            "id": serial_id,
        },
    )
    return serial_id


def test_modele_des_revues(sa_sync_conn):
    conn = sa_sync_conn
    free = _serial(conn, "Libre", is_oa=True, in_doaj=True, fees=("No", "No"))
    free_closed = _serial(
        conn, "Libre, fermée pour OpenAlex", is_oa=False, in_doaj=True, fees=("No", "No")
    )
    other_fees = _serial(conn, "Frais", is_oa=True, in_doaj=True, fees=("No", "Yes"))
    lost_diamond = _serial(
        conn, "Payante", oa_model="diamond", is_oa=True, in_doaj=True, fees=("Yes", "No")
    )
    left_doaj = _serial(conn, "Sortie du DOAJ", oa_model="diamond", is_oa=True, fees=("No", "No"))
    hub = _serial(conn, "Hub", is_oa=True)
    add_to_serial_list(conn, hub, "ddh")
    subscription = _serial(conn, "Abonnement", oa_model="full_oa", is_oa=False)
    absent = _serial(conn, "Absente d'OpenAlex", oa_model="subscription")
    manual = _serial(conn, "Manuelle", oa_model="diamond", is_oa=False, manual=True)

    assert model_serials(conn) == 8

    ids = [
        free,
        free_closed,
        other_fees,
        lost_diamond,
        left_doaj,
        hub,
        subscription,
        absent,
        manual,
    ]
    models = dict(
        conn.execute(
            text("SELECT id, oa_model::text FROM serials WHERE id = ANY(:ids)"), {"ids": ids}
        ).all()
    )
    assert models == {
        free: "diamond",
        free_closed: "diamond",
        other_fees: "full_oa",
        lost_diamond: "full_oa",
        left_doaj: "full_oa",
        hub: "diamond",
        subscription: "subscription",
        absent: None,
        manual: "diamond",
    }
