"""Reconnaissance des structures dans un texte normalisé, par leurs formes de nom (`structure_name_forms`).

Sert à la résolution des adresses, à celle des laboratoires partenaires de thèse et aux scripts qui identifient des structures dans un libellé.
"""

from typing import NamedTuple, Self

import ahocorasick
from sqlalchemy import Connection, text

from domain.structures.structure import StructureType


class MatchableNameForm(NamedTuple):
    """Forme normalisée d'une structure, avec ses options de reconnaissance.

    Une forme qui demande un contexte vaut seulement si l'une des structures de ce contexte est aussi reconnue dans le texte : un code de laboratoire ambigu vaut seulement avec son université de tutelle. Une forme d'exclusion présente retire sa structure du résultat, quelles que soient ses autres formes. Le type de la structure dit si sa reconnaissance vaut affiliation ou seulement contexte (`StructureType.is_affiliation`).
    """

    id: int
    structure_id: int
    form_text: str
    is_word_boundary: bool
    requires_context_of: list[int] | None
    is_excluding: bool
    structure_type: StructureType


class StructureMatch(NamedTuple):
    """Structure reconnue dans un texte, avec la forme de nom à l'origine."""

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
    """Vrai si la sous-chaîne de `start` à `end` inclus est un mot entier : bord du texte ou caractère non alphanumérique de part et d'autre."""
    before_ok = start == 0 or not text[start - 1].isalnum()
    after_ok = end + 1 >= len(text) or not text[end + 1].isalnum()
    return before_ok and after_ok


class StructureNameMatcher:
    """Reconnaît les structures dans un texte par leurs formes de nom.

    Un automate Aho-Corasick détecte toutes les formes en un seul passage par texte, quel que soit leur nombre.
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
        """Reconnaissance sur les formes de nom de toutes les structures."""
        return cls(load_name_forms(conn))

    def _matched_form_ids(self, text_normalized: str) -> set[int]:
        """Formes présentes dans le texte, comme mot entier pour celles qui l'exigent."""
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
        """Structures reconnues dans un texte normalisé, avec la forme de nom à l'origine de chacune.

        Une structure est reconnue par une forme présente, hors exclusion, dont le contexte est une structure reconnue. Les contextes s'enchaînent : le calcul se répète tant qu'une structure s'ajoute. Pour chaque structure, la première forme valide par `id` l'emporte.

        Les structures sans valeur d'affiliation (sites) servent de contexte sans figurer au résultat.
        """
        matched_ids = self._matched_form_ids(text_normalized)
        if not matched_ids:
            return []
        matched = sorted((self._forms_by_id[i] for i in matched_ids), key=lambda f: f.id)
        excluded = {f.structure_id for f in matched if f.is_excluding}
        candidates = [f for f in matched if f.structure_id not in excluded]

        recognized: dict[int, int] = {}  # structure reconnue → forme retenue
        changed = True
        while changed:
            changed = False
            for f in candidates:
                if f.structure_id in recognized and recognized[f.structure_id] <= f.id:
                    continue
                ctx = f.requires_context_of
                if ctx and not any(cid in recognized for cid in ctx):
                    continue
                recognized[f.structure_id] = f.id
                changed = True

        return [
            StructureMatch(sid, form_id)
            for sid, form_id in sorted(recognized.items(), key=lambda kv: kv[1])
            if self._forms_by_id[form_id].structure_type.is_affiliation
        ]
