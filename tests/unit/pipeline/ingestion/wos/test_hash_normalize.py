"""Empreinte de changement d'une ligne d'export WoS : indifférente à la date d'export et aux compteurs d'usage, sensible au contenu de l'enregistrement source."""

from pipeline.ingestion.common.change_detection import change_detection_hash

_ROW = {"UT": "WOS:1", "TI": "Un titre", "TC": "3", "DA": "2026-10-07", "U1": "2", "U2": "5"}


def test_date_et_usage_ignores():
    autre_export = {**_ROW, "DA": "2026-11-02", "U1": "4", "U2": "9"}
    assert change_detection_hash("wos", autre_export) == change_detection_hash("wos", _ROW)


def test_enregistrement_source_modifie_detecte():
    assert change_detection_hash("wos", {**_ROW, "TC": "4"}) != change_detection_hash("wos", _ROW)


def test_payload_api_inchange():
    api = {"UID": "WOS:1", "static_data": {}, "DA": "x"}
    assert change_detection_hash("wos", api) != change_detection_hash("wos", {**api, "DA": "y"})
