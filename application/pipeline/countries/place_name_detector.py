"""Détection de noms de lieux dans une adresse via un automate Aho-Corasick.

Les formes `place_name_forms` de `kind IN ('institution', 'city')` (universités, CHU, villes…) sont des expressions multi-mots associées chacune à un pays. On les cherche comme sous-chaînes du `normalized_text` d'une adresse — n'importe où, pas seulement en fin de segment — pour poser le pays d'adresses sans pays explicite.

Match **au mot près** : les motifs et le texte sont encadrés d'espaces, donc « universite lyon » ne matche pas « luniversite lyonx ». L'automate balaie chaque adresse en un seul passage, quel que soit le nombre de formes.
"""

from collections.abc import Mapping

import ahocorasick


class PlaceNameDetector:
    """Détecte les pays des lieux (institutions, villes) présents dans une adresse.

    `forms` : `{form_normalized: iso_code}` (codes pays minuscules canoniques). `detect` rend l'ensemble des pays des lieux matchés — vide si aucun. Un appelant autoritaire n'écrit `countries` que si l'ensemble est un singleton.
    """

    def __init__(self, forms: Mapping[str, str]) -> None:
        self._automaton = ahocorasick.Automaton()
        for form, iso in forms.items():
            if form:
                self._automaton.add_word(f" {form} ", iso)
        self._empty = len(self._automaton) == 0
        if not self._empty:
            self._automaton.make_automaton()

    def detect(self, normalized_text: str) -> set[str]:
        if self._empty or not normalized_text:
            return set()
        return {iso for _end, iso in self._automaton.iter(f" {normalized_text} ")}
