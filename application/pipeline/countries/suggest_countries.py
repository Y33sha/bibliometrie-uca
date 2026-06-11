"""Suggestion de pays par adresse via un automate Aho-Corasick inversé.

Pour les adresses sans pays, on cherche dans le pool des adresses *avec* pays
celles dont le `normalized_text` contient la cible comme sous-chaîne, et on
retient le ou les pays les plus fréquents parmi elles.

Au lieu d'une recherche trigram par cible (une requête SQL par adresse, lente),
on **inverse la boucle** : les cibles deviennent les motifs d'un automate
Aho-Corasick, le pool devient les textes. Un seul passage sur le pool ressort,
pour chaque adresse-pool, toutes les cibles qu'elle contient — coût indépendant
du nombre de cibles. L'automate est construit par batch de cibles pour borner
la mémoire ; le pool est rescanné à chaque batch.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

import ahocorasick


class CountrySuggester:
    """Suggère un pays par cible (match sous-chaîne) via un automate sur un batch de cibles.

    `targets` : `(address_id, normalized_text)` des adresses sans pays à suggérer.
    Plusieurs adresses peuvent partager le même `normalized_text` (dédoublonnage
    par md5(raw_text), pas par texte normalisé) : chaque motif porte la liste des
    ids concernés.
    """

    def __init__(self, targets: list[tuple[int, str]]) -> None:
        by_text: dict[str, list[int]] = defaultdict(list)
        for target_id, normalized_text in targets:
            if normalized_text:
                by_text[normalized_text].append(target_id)
        self._automaton = ahocorasick.Automaton()
        for normalized_text, ids in by_text.items():
            self._automaton.add_word(normalized_text, ids)
        self._empty = not by_text
        if not self._empty:
            self._automaton.make_automaton()

    def suggest(self, pool: Iterable[tuple[str, Sequence[str] | None]]) -> dict[int, list[str]]:
        """Balaie le pool `(normalized_text, countries)` et rend `{target_id: [pays]}`.

        Par cible matchée : le ou les pays les plus fréquents (ex-aequo triés)
        parmi les adresses-pool qui la contiennent comme sous-chaîne. Une adresse
        sans aucun match est absente du résultat (le caller lui pose un array vide).
        Chaque adresse-pool ne compte qu'une fois par cible, quelles que soient
        les positions du match.
        """
        counts: dict[int, Counter[str]] = defaultdict(Counter)
        if not self._empty:
            for normalized_text, countries in pool:
                if not normalized_text or not countries:
                    continue
                codes = [c.strip() for c in countries if c and c.strip()]
                if not codes:
                    continue
                matched: set[int] = set()
                for _end, ids in self._automaton.iter(normalized_text):
                    matched.update(ids)
                for target_id in matched:
                    counts[target_id].update(codes)

        result: dict[int, list[str]] = {}
        for target_id, counter in counts.items():
            top = max(counter.values())
            result[target_id] = sorted({code for code, n in counter.items() if n == top})
        return result
