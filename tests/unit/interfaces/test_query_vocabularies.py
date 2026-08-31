"""Toute liste de valeurs reçue en query string est prise dans un vocabulaire fermé, ou motivée.

Une valeur séparée par des virgules échappe à la validation de FastAPI : c'est le code de la route qui la découpe, et rien n'oblige à en vérifier le contenu. Une valeur inconnue laissée passer ne provoque pas d'erreur — elle traverse jusqu'au constructeur de clause SQL, qui l'ignore, et la lecture rend alors un ensemble plus large que celui qu'on croit avoir demandé, sous un code 200.

Fermer chaque vocabulaire est le remède ; s'en souvenir à chaque paramètre ajouté n'en est pas un. Ce module confronte donc le code à la liste : `parse_str_csv` rend une liste de chaînes sans rien vérifier, et chacun de ses appels dans les routes doit figurer ci-dessous, motivé. Un paramètre ajouté sans vocabulaire fait échouer l'intégration.

Les vocabulaires fermés eux-mêmes sont exercés par la surface HTTP (`tests/integration/interfaces/test_query_vocabularies_api.py`), qui vérifie qu'une valeur intruse rend 422.
"""

import re

from infrastructure import PROJECT_ROOT

_ROUTES = PROJECT_ROOT / "interfaces" / "api" / "routers"
_APPEL = re.compile(r"parse_str_csv\(\s*([^),]+?)\s*\)")

LISTES_LIBRES: dict[tuple[str, str], str] = {
    ("publications.py", "lab_id"): (
        "Découpage préalable : la sentinelle `none` est mise de côté, et ce qui reste passe par "
        "`parse_ints`, qui refuse ce qui n'est pas un identifiant."
    ),
    ("publications.py", "self.country"): (
        "Codes pays présents dans les données, non énumérables dans le code. La valeur est liée "
        "à une comparaison de tableaux : une valeur inconnue ne rend aucune ligne, au lieu "
        "d'annuler le filtre."
    ),
    ("publishers.py", "country"): (
        "Mêmes codes pays que la liste des publications, même liaison, même comportement."
    ),
    ("persons.py", "department"): (
        "Libellés de départements issus de l'extraction du référentiel des personnels : ils "
        "vivent dans les données, pas dans le code."
    ),
    ("persons.py", "role"): "Fonctions issues de la même extraction, pour la même raison.",
}
"""Appels à `parse_str_csv` dans les routes, et ce qui justifie l'absence de vocabulaire fermé.

Clé : le fichier de route et l'expression passée à l'appel. Y inscrire une entrée est un geste délibéré — la question à trancher étant « puis-je énumérer les valeurs admises ? », et la réponse « non » demandant de dire pourquoi.
"""


def _appels_dans_les_routes() -> set[tuple[str, str]]:
    """Appels à `parse_str_csv` écrits dans les modules de route, par fichier et argument."""
    appels: set[tuple[str, str]] = set()
    for fichier in _ROUTES.glob("*.py"):
        for argument in _APPEL.findall(fichier.read_text(encoding="utf-8")):
            appels.add((fichier.name, argument))
    return appels


class TestListesLibres:
    def test_chaque_liste_sans_vocabulaire_est_motivee(self):
        """Un paramètre à valeurs multiples ajouté sans vocabulaire fermé fait échouer l'intégration."""
        non_motives = _appels_dans_les_routes() - set(LISTES_LIBRES)
        assert not non_motives, (
            f"Listes de valeurs sans vocabulaire fermé ni motif : {sorted(non_motives)}. "
            "Les prendre dans un vocabulaire fermé (`parse_vocabulary_csv`), ou les inscrire "
            "ici avec la raison pour laquelle leurs valeurs ne s'énumèrent pas."
        )

    def test_la_liste_ne_porte_pas_de_motif_devenu_inutile(self):
        """Un paramètre fermé depuis, ou retiré, sort de la liste : elle décrit le code, non son passé."""
        obsoletes = set(LISTES_LIBRES) - _appels_dans_les_routes()
        assert not obsoletes, sorted(obsoletes)

    def test_chaque_motif_dit_quelque_chose(self):
        for cle, motif in LISTES_LIBRES.items():
            assert len(motif) > 40, cle


class TestVocabulairesFermes:
    """Les vocabulaires que les routes opposent aux paramètres, et d'où ils viennent."""

    def test_les_valeurs_du_filtre_par_source_derivent_du_registre(self):
        """Le vocabulaire se calcule depuis les préfixes plutôt que de s'écrire à côté d'eux : une source ajoutée au registre entre dans le filtre sans autre geste."""
        from domain.sources.registry import SOURCE_FILTER_PREFIXES, SOURCE_FILTER_VALUES

        assert SOURCE_FILTER_VALUES == {
            f"{prefixe}_{presence}"
            for prefixe in SOURCE_FILTER_PREFIXES
            for presence in ("yes", "no")
        }

    def test_les_prefixes_de_source_designent_des_sources_du_registre(self):
        from domain.sources.registry import ALL_SOURCES_SET, SOURCE_FILTER_PREFIXES

        assert {s.value for s in SOURCE_FILTER_PREFIXES.values()} <= ALL_SOURCES_SET

    def test_les_origines_apc_exigeant_un_laboratoire_font_partie_du_vocabulaire(self):
        from application.ports.read_models.publications_queries import (
            APC_ORIGINS,
            APC_ORIGINS_NEEDING_LAB,
        )

        assert APC_ORIGINS_NEEDING_LAB < APC_ORIGINS
