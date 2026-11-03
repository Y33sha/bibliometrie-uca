from pathlib import Path

from interfaces.cli.reporting.scimago import latest_scimago_file, read_scimago_ranking

HEADER = "Rank;Sourceid;Title;Type;Issn;SJR Best Quartile;Total Docs. (2025);Categories\n"


def _write(path: Path, *rows: str) -> Path:
    path.write_text(HEADER + "".join(f"{r}\n" for r in rows), encoding="utf-8")
    return path


def test_reads_year_and_quartiles_by_category(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "scimagojr 2025.csv",
        '1;1;"Cancer";journal;"15424863, 00079235";Q1;48;"Hematology (Q1); Oncology (Q2)"',
    )
    ranking = read_scimago_ranking(path)
    assert ranking.year == 2025
    assert ranking.quartiles["1542-4863"] == {"Hematology": "Q1", "Oncology": "Q2"}
    assert ranking.quartiles["0007-9235"] == {"Hematology": "Q1", "Oncology": "Q2"}


def test_q1_issns_and_categories(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "scimagojr 2025.csv",
        '1;1;"Cancer";journal;"15424863";Q1;48;"Oncology (Q1); Hematology (Q1); Surgery (Q2)"',
        '2;2;"Other";journal;"00079235";Q3;48;"Surgery (Q3)"',
    )
    ranking = read_scimago_ranking(path)
    assert ranking.q1_issns() == ["1542-4863"]
    assert ranking.q1_categories(["1542-4863", "0007-9235"]) == ["Hematology", "Oncology"]
    assert ranking.q1_categories(["0007-9235"]) == []


def test_ignores_other_types_and_unranked_categories(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "scimagojr 2025.csv",
        '1;1;"Series";book series;"15424863";Q1;48;"Oncology (Q1)"',
        '2;2;"New";journal;"00079235";-;48;"Oncology"',
    )
    assert read_scimago_ranking(path).quartiles == {}


def test_latest_file_is_the_most_recent_year(tmp_path: Path) -> None:
    for year in (2023, 2025, 2024):
        (tmp_path / f"scimagojr {year}.csv").touch()
    assert latest_scimago_file(tmp_path) == tmp_path / "scimagojr 2025.csv"
    assert latest_scimago_file(tmp_path / "absent") is None
