"""Lecture du classement des revues de SCImago (https://www.scimagojr.com/journalrank.php).

SCImago publie un fichier CSV par année : quartile de chaque revue dans chacune de ses catégories, calculé sur Scopus. Le site refuse le téléchargement automatisé, donc le fichier est déposé à la main dans `SCIMAGO_DIR`. Les rapports lisent le fichier à chaque exécution.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from domain.documents.identifiers import ISSN

SCIMAGO_DIR = Path("data/imports/scimago")
"""Dossier des fichiers SCImago, nommés `scimagojr AAAA.csv`."""

Q1 = "Q1"

JOURNAL_TYPE = "journal"
"""Valeur de la colonne `Type` pour une revue. Les autres valeurs désignent les collections d'ouvrages, les actes de conférences et les revues professionnelles."""

_YEAR_COLUMN_RE = re.compile(r"Total Docs\. \((\d{4})\)")
"""Colonne du nombre de documents de l'année du classement."""

_CATEGORY_RE = re.compile(r"(.+) \((Q[1-4])\)")
"""Catégorie de la colonne `Categories`, avec le quartile de la revue : `Oncology (Q1)`."""


@dataclass(frozen=True, slots=True)
class ScimagoRanking:
    year: int
    quartiles: Mapping[str, Mapping[str, str]]
    """Quartile de chaque revue dans chacune de ses catégories, par ISSN normalisé."""

    def q1_issns(self) -> list[str]:
        """ISSN des revues Q1 dans au moins une catégorie."""
        return sorted(
            issn for issn, by_category in self.quartiles.items() if Q1 in by_category.values()
        )

    def q1_categories(self, issns: Collection[str]) -> list[str]:
        """Catégories où la revue des ISSN `issns` est Q1, par ordre alphabétique."""
        return sorted(
            {
                category
                for issn in issns
                for category, quartile in self.quartiles.get(issn, {}).items()
                if quartile == Q1
            }
        )


def latest_scimago_file(directory: Path = SCIMAGO_DIR) -> Path | None:
    """Fichier SCImago de l'année la plus récente du dossier, `None` si le dossier n'en contient aucun."""
    files = sorted(directory.glob("scimagojr *.csv"))
    return files[-1] if files else None


def read_scimago_ranking(path: Path) -> ScimagoRanking:
    """Lit les quartiles par catégorie des revues du fichier. Les entrées d'un autre type que revue sont ignorées. Un ISSN présent dans plusieurs lignes réunit leurs catégories."""
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        year = _ranking_year(reader.fieldnames or ())
        quartiles: dict[str, dict[str, str]] = {}
        for row in reader:
            if row["Type"] != JOURNAL_TYPE:
                continue
            by_category = {
                m.group(1): m.group(2)
                for raw in row["Categories"].split(";")
                if (m := _CATEGORY_RE.fullmatch(raw.strip()))
            }
            if not by_category:
                continue
            for raw in row["Issn"].split(","):
                if (issn := ISSN.try_parse(raw)) is not None:
                    quartiles.setdefault(str(issn), {}).update(by_category)
    return ScimagoRanking(year, quartiles)


def _ranking_year(columns: Sequence[str]) -> int:
    for column in columns:
        if m := _YEAR_COLUMN_RE.fullmatch(column):
            return int(m.group(1))
    raise ValueError("Fichier SCImago sans colonne « Total Docs. (AAAA) »")
