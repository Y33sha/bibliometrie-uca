"""Poids en bits du modèle du résidu, par comparaison et par niveau (`domain.publications.author_grouping.comparison_levels`).

Estimés le 2026-10-18 par Splink, par EM sur les contributions sources laissées sans lien par la règle de noms dans tout le stock, 100 itérations. Les poids d'ORCID et d'IdRef viennent d'un modèle estimé sur toutes les paires de contributions sources des publications de 100 auteurs au plus : sur le résidu, l'EM ne les identifie pas.
"""

RESIDUAL_WEIGHTS: dict[str, dict[str, float]] = {
    "ln": {
        "Exact match on ln": 8.846,
        "mots inclus": 9.199,
        "jw 0.92": 7.81,
        "jw 0.8": 6.204,
        "else": -1.067,
    },
    "fn": {
        "Exact match on fn": 3.574,
        "initiales concordantes": 2.849,
        "jw 0.9": 3.527,
        "else": -0.561,
    },
    "orcid": {"exact": 12.346, "else": -6.778},
    "idref": {"exact": 11.994, "else": -6.521},
    "gap": {"même trou": 5.435, "trou voisin": 3.325, "ailleurs": -0.773},
}
