"""Reconnaissance des structures dans un texte normalisé, par leurs formes de nom (`structure_name_forms`).

Sert à la résolution des adresses, à celle des laboratoires partenaires de thèse et aux scripts qui identifient des structures dans un libellé.
"""

from typing import NamedTuple, Self

import ahocorasick
from sqlalchemy import Connection, text

from domain.structures.structure import StructureType


class MatchableNameForm(NamedTuple):
    """Forme normalisée d'une structure, avec ses options de reconnaissance.

    `requires_context_of` : liste des structure_ids dont au moins une forme doit aussi matcher pour valider cette forme (anti-faux-positifs cross-établissement : un code de laboratoire ambigu n'est retenu que si son université de tutelle matche le même texte). `None` ou liste vide = pas de contexte requis.
    `is_excluding` : si TRUE et que la forme matche, retire la structure des résultats même si d'autres formes la matchent.
    `structure_type` : type de la structure de la forme. Détermine si un appariement vaut affiliation à retenir ou seulement contexte de reconnaissance (`StructureType.is_affiliation`).
    """

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    requires_context_of: list[int] | None
    is_excluding: bool
    structure_type: StructureType


class StructureMatch(NamedTuple):
    """Structure `structure_id` reconnue dans un texte par sa forme `form_id`."""

    structure_id: int
    form_id: int


def load_name_forms(conn: Connection) -> list[MatchableNameForm]:
    """Formes de nom de toutes les structures, par `id` croissant."""
    rows = conn.execute(
        text("""
            SELECT nf.id, nf.structure_id, nf.form_text,
                   nf.is_word_boundary, nf.requires_context_of, nf.is_excluding,
                   s.structure_type::text AS structure_type
            FROM structure_name_forms nf
            JOIN structures s ON s.id = nf.structure_id
            ORDER BY nf.id
        """)
    ).all()
    return [
        MatchableNameForm(
            id=r.id,
            structure_id=r.structure_id,
            form_text=r.form_text,
            is_word_boundary=r.is_word_boundary,
            requires_context_of=r.requires_context_of,
            is_excluding=r.is_excluding,
            structure_type=StructureType(r.structure_type),
        )
        for r in rows
    ]


def _is_whole_word(text: str, start: int, end: int) -> bool:
    """Vrai si `text[start:end+1]` est un mot entier : bord de chaîne ou caractère non alphanumérique de part et d'autre."""
    before_ok = start == 0 or not text[start - 1].isalnum()
    after_ok = end + 1 >= len(text) or not text[end + 1].isalnum()
    return before_ok and after_ok


class StructureNameMatcher:
    """Matche les formes de structures dans un texte via un automate Aho-Corasick.

    L'automate, construit une fois sur l'ensemble des formes, détecte en un seul passage par texte toutes les formes présentes (coût indépendant du nombre de formes).
    """

    def __init__(self, forms: list[MatchableNameForm]) -> None:
        self._forms_by_id = {f.id: f for f in forms}
        by_text: dict[str, list[MatchableNameForm]] = {}
        for f in forms:
            if f.form_text:
                by_text.setdefault(f.form_text, []).append(f)
        self._automaton = ahocorasick.Automaton()
        for form_text, matching_forms in by_text.items():
            self._automaton.add_word(form_text, matching_forms)
        self._empty = not by_text
        if not self._empty:
            self._automaton.make_automaton()

    @classmethod
    def load(cls, conn: Connection) -> Self:
        """Matcher construit sur les formes de nom de toutes les structures."""
        return cls(load_name_forms(conn))

    def _matched_form_ids(self, text_normalized: str) -> set[int]:
        """Ids des formes présentes (sous-chaîne + contrainte de mot entier)."""
        matched: set[int] = set()
        if self._empty:
            return matched
        for end, forms_here in self._automaton.iter(text_normalized):
            for f in forms_here:
                if f.id in matched:
                    continue
                if not f.is_word_boundary or _is_whole_word(
                    text_normalized, end - len(f.form_text) + 1, end
                ):
                    matched.add(f.id)
        return matched

    def resolve(self, text_normalized: str) -> list[StructureMatch]:
        """Résout un texte normalisé : affiliations reconnues et forme à l'origine.

        Pour chaque structure, la première forme par `id` qui matche l'emporte.

        Les structures dont le type ne vaut pas affiliation participent à l'arbitrage sans figurer au résultat : elles entrent dans `structs_matched`, donc satisfont le `requires_context_of` des formes qui les invoquent, mais ne produisent aucun rattachement.
        """
        matched_ids = self._matched_form_ids(text_normalized)
        if not matched_ids:
            return []
        matched = [self._forms_by_id[i] for i in matched_ids]
        structs_matched = {f.structure_id for f in matched}
        excluded = {f.structure_id for f in matched if f.is_excluding}

        result: list[StructureMatch] = []
        seen: set[int] = set()
        for f in sorted(matched, key=lambda f: f.id):
            sid = f.structure_id
            if sid in seen or sid in excluded or f.is_excluding:
                continue
            if not f.structure_type.is_affiliation:
                continue
            ctx = f.requires_context_of
            if ctx and not any(cid in structs_matched for cid in ctx):
                continue
            result.append(StructureMatch(sid, f.id))
            seen.add(sid)
        return result
