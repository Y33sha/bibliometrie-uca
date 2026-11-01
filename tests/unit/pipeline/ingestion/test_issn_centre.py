"""Lecture de la table ISSN-L de l'ISSN International Centre (`pipeline.ingestion.complements.issn_centre`)."""

import zipfile

from pipeline.ingestion.complements.issn_centre import read_issnl_table


def _zip(tmp_path, files: dict[str, str]) -> str:
    path = tmp_path / "issnltables.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return str(path)


def test_lit_les_couples_du_fichier_issn_vers_issnl(tmp_path):
    path = _zip(
        tmp_path,
        {
            "20261031.ISSN-L-to-ISSN.txt": "ISSN-L\tISSN\n2469-9985\t2469-9985\t2469-9993\n",
            "20261031.ISSN-to-ISSN-L.txt": "ISSN\tISSN-L\n2469-9993\t2469-9985\tta\n0735-703x\t1939-2087\n",
        },
    )

    assert list(read_issnl_table(path)) == [
        ("ISSN", "ISSN-L"),
        ("2469-9993", "2469-9985"),
        ("0735-703X", "1939-2087"),
    ]


def test_un_zip_sans_le_fichier_ne_donne_aucun_couple(tmp_path):
    path = _zip(tmp_path, {"lisezmoi.txt": "rien"})

    assert list(read_issnl_table(path)) == []
