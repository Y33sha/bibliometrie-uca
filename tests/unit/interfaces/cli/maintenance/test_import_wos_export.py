"""Tests de la lecture des exports tabulés de `interfaces.cli.maintenance.import_wos_export`."""

from interfaces.cli.maintenance.import_wos_export import export_files, read_export

_HEADER = "PT\tAU\tTI\tDI\tUT\n"


def test_lignes_reduites_aux_balises_non_vides(tmp_path):
    export = tmp_path / "2025.txt"
    export.write_text(
        "﻿" + _HEADER + 'J\tDoe, J\tUn "titre"\t\tWOS:1\r\nJ\t\tSans UT\t10.1/x\t\r\n',
        encoding="utf-8",
    )
    assert list(read_export(export)) == [
        {"PT": "J", "AU": "Doe, J", "TI": 'Un "titre"', "UT": "WOS:1"}
    ]


def test_fichiers_d_un_repertoire_tries(tmp_path):
    for name in ("b.txt", "a.txt", "notes.md"):
        (tmp_path / name).write_text(_HEADER, encoding="utf-8")
    seul = tmp_path / "seul.tsv"
    seul.write_text(_HEADER, encoding="utf-8")
    assert [p.name for p in export_files([tmp_path, seul])] == ["a.txt", "b.txt", "seul.tsv"]
