"""Toute liste de valeurs reçue en query string est prise dans un vocabulaire fermé, ou motivée.

Une valeur séparée par des virgules échappe à la validation de FastAPI : le code de la route la découpe, sans obligation d'en vérifier le contenu. Une valeur inconnue traverse jusqu'au constructeur de clause SQL, qui l'ignore. La lecture renvoie alors, sous un code 200, un ensemble plus large que celui demandé.

`parse_str_csv` renvoie une liste de chaînes sans vérification. Chacun de ses appels dans l'API figure donc ci-dessous, avec son motif. Un paramètre ajouté sans vocabulaire fermé fait échouer ce test.

Les vocabulaires fermés sont testés par la surface HTTP (`tests/integration/interfaces/test_query_vocabularies_api.py`), qui vérifie qu'une valeur intruse donne 422.
"""

import re

from infrastructure import PROJECT_ROOT

_API = PROJECT_ROOT / "interfaces" / "api"
# Module qui définit `parse_str_csv`.
_DEFINITION = _API / "filters.py"
_APPEL = re.compile(r"parse_str_csv\(\s*([^),]+?)\s*\)")

LISTES_LIBRES: dict[tuple[str, str], str] = {
    ("publication_filters.py", "self.country"): (
        "Codes pays présents dans les données, non énumérables dans le code. La valeur est liée "
        "à une comparaison de tableaux : une valeur inconnue ne rend aucune ligne, au lieu "
        "d'annuler le filtre."
    ),
    ("publication_filters.py", "self.language"): (
        "Codes du référentiel des langues, qui vit dans les données et non dans le code. La "
        "valeur est liée à une comparaison `= ANY` : une valeur inconnue ne rend aucune ligne, "
        "au lieu d'annuler le filtre."
    ),
    ("publishers.py", "country"): (
        "Mêmes codes pays que la liste des publications, même liaison, même comportement."
    ),
    ("structures.py", "country"): (
        "Mêmes codes pays que la liste des publications, liés à une comparaison `= ANY` : une "
        "valeur inconnue ne rend aucune ligne, au lieu d'annuler le filtre."
    ),
    ("persons.py", "department"): (
        "Libellés de départements issus de l'extraction du référentiel des personnels : ils "
        "vivent dans les données, pas dans le code."
    ),
    ("persons.py", "role"): "Fonctions issues de la même extraction, pour la même raison.",
}
"""Appels à `parse_str_csv` dans l'API, et ce qui justifie l'absence de vocabulaire fermé.

Clé : le module et l'expression passée à l'appel. Une entrée répond « non » à la question « puis-je énumérer les valeurs admises ? », et dit pourquoi.
"""


def _appels_dans_les_routes() -> set[tuple[str, str]]:
    """Appels à `parse_str_csv` écrits dans les modules de l'API, par fichier et argument."""
    appels: set[tuple[str, str]] = set()
    for fichier in _API.rglob("*.py"):
        if fichier == _DEFINITION:
            continue
        for argument in _APPEL.findall(fichier.read_text(encoding="utf-8")):
            appels.add((fichier.name, argument))
    return appels


class TestListesLibres:
    def test_chaque_liste_sans_vocabulaire_est_motivee(self):
        """Un paramètre à valeurs multiples sans vocabulaire fermé a un motif dans `LISTES_LIBRES`."""
        non_motives = _appels_dans_les_routes() - set(LISTES_LIBRES)
        assert not non_motives, (
            f"Listes de valeurs sans vocabulaire fermé ni motif : {sorted(non_motives)}. "
            "Les prendre dans un vocabulaire fermé (`parse_vocabulary_csv`), ou les inscrire "
            "ici avec la raison pour laquelle leurs valeurs ne s'énumèrent pas."
        )

    def test_la_liste_ne_porte_pas_de_motif_devenu_inutile(self):
        """Chaque entrée de la liste correspond à un appel présent dans le code."""
        obsoletes = set(LISTES_LIBRES) - _appels_dans_les_routes()
        assert not obsoletes, sorted(obsoletes)

    def test_chaque_motif_dit_quelque_chose(self):
        for cle, motif in LISTES_LIBRES.items():
            assert len(motif) > 40, cle


class TestVocabulairesFermes:
    """Les vocabulaires que les routes opposent aux paramètres, et d'où ils viennent."""

    def test_les_valeurs_du_filtre_par_source_derivent_du_registre(self):
        """Le vocabulaire se calcule depuis les préfixes : une source ajoutée au registre entre dans le filtre sans autre modification."""
        from domain.sources.registry import SOURCE_FILTER_PREFIXES, SOURCE_FILTER_VALUES

        assert SOURCE_FILTER_VALUES == {
            f"{prefixe}_{presence}"
            for prefixe in SOURCE_FILTER_PREFIXES
            for presence in ("yes", "no")
        }

    def test_les_prefixes_de_source_designent_des_sources_du_registre(self):
        from domain.sources.registry import ALL_SOURCES_SET, SOURCE_FILTER_PREFIXES

        assert {s.value for s in SOURCE_FILTER_PREFIXES.values()} <= ALL_SOURCES_SET
