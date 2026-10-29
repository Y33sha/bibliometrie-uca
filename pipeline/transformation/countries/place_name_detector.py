"""Détection de noms de lieux dans une adresse via un automate Aho-Corasick.

Les formes `place_name_forms` de `kind IN ('institution', 'city')` (universités, CHU, villes…) sont des expressions de plusieurs mots, associées chacune à un pays. Elles se cherchent n'importe où dans le `normalized_text` d'une adresse.

La comparaison se fait au mot près : motifs et texte sont encadrés d'espaces, et « universite lyon » est absent de « luniversite lyonx ». L'automate parcourt chaque adresse en un seul passage, quel que soit le nombre de formes.
"""

from collections.abc import Mapping

import ahocorasick


class PlaceNameDetector:
    """Détecte les pays des lieux (institutions, villes) présents dans une adresse.

    `forms` : `{form_normalized: iso_code}` (codes pays ISO en minuscules). `detect` rend l'ensemble des pays des lieux matchés, vide si aucun.
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
