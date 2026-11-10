"""Lecture d'une famille de brevets INPADOC reçue d'OPS (`ops:patent-family`).

Un membre de la famille est une publication : une demande publiée (code de type A), ou un brevet délivré (code B). Il cite sa demande et les priorités qu'elle revendique. Les numéros suivent le format docdb de l'Office européen des brevets : office, puis numéro, sans code de type. Une demande internationale (code W) s'écrit sous l'office WO, sans office de dépôt (`FR2017051773` → `WO2017051773`), comme le lit `domain.documents.patent_numbers`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from domain.normalize import normalize_text
from domain.types import JsonValue, as_mapping, as_sequence, as_str

_COUNTRY_SUFFIX_RE = re.compile(r"\s*\[[A-Z]{2}\]\s*$")
"""Pays ajouté au nom d'un déposant ou d'un inventeur au format epodoc (`UNIV CLERMONT AUVERGNE [FR]`)."""


def items(value: JsonValue) -> list[JsonValue]:
    """Renvoie les éléments d'un nœud JSON d'OPS : une liste, ou un objet seul quand il n'y a qu'un élément."""
    if isinstance(value, Mapping):
        return [value]
    return list(as_sequence(value))


def _text(node: JsonValue) -> str | None:
    """Renvoie le texte d'un nœud JSON d'OPS (`{"$": "…"}`), ou la chaîne elle-même."""
    return as_str(as_mapping(node).get("$")) if isinstance(node, Mapping) else as_str(node)


def _date(value: str | None) -> date | None:
    if value and len(value) == 8 and value.isdigit():
        return date(int(value[:4]), int(value[4:6]), int(value[6:]))
    return None


@dataclass(frozen=True, slots=True)
class DocId:
    """Document docdb : office, numéro, code de type, date."""

    country: str
    number: str
    kind: str | None
    date: date | None

    @property
    def is_international_application(self) -> bool:
        return self.kind == "W"

    @property
    def is_grant(self) -> bool:
        """Brevet délivré : code B, ou C pour le Canada."""
        kind = self.kind or ""
        return kind.startswith("B") or (self.country == "CA" and kind.startswith("C"))

    @property
    def identifier(self) -> str:
        """Numéro sans code de type, sous l'office WO pour une demande internationale."""
        return (
            f"WO{self.number}"
            if self.is_international_application
            else f"{self.country}{self.number}"
        )


def _docdb(ids: JsonValue) -> DocId | None:
    """Renvoie le document docdb d'une liste de `document-id`, avec la date de l'entrée epodoc à défaut."""
    entries = [as_mapping(d) for d in items(ids)]
    epodoc_date = next(
        (_text(d.get("date")) for d in entries if d.get("@document-id-type") == "epodoc"), None
    )
    for d in entries:
        if d.get("@document-id-type") == "docdb":
            country, number = _text(d.get("country")), _text(d.get("doc-number"))
            if country and number:
                return DocId(
                    country,
                    number,
                    _text(d.get("kind")),
                    _date(_text(d.get("date")) or epodoc_date),
                )
    return None


@dataclass(frozen=True, slots=True)
class Party:
    """Déposant ou inventeur, sous l'un des formats de nom d'OPS (`original` ou `epodoc`)."""

    name: str
    original: bool

    @property
    def normalized(self) -> str:
        """Forme de comparaison du nom, sans le pays du format epodoc."""
        return normalize_text(_COUNTRY_SUFFIX_RE.sub("", self.name))


@dataclass(frozen=True, slots=True)
class Text:
    """Titre ou résumé, avec sa langue."""

    lang: str | None
    value: str


@dataclass(frozen=True, slots=True)
class Member:
    """Publication de la famille."""

    publication: DocId | None
    application: DocId | None
    priorities: tuple[DocId, ...]
    titles: tuple[Text, ...]
    abstracts: tuple[Text, ...]
    applicants: tuple[Party, ...]
    inventors: tuple[Party, ...]
    cpc: tuple[str, ...]


def _parties(biblio: Mapping[str, JsonValue], group: str, person: str) -> tuple[Party, ...]:
    out = []
    for raw in items(as_mapping(as_mapping(biblio.get("parties")).get(group)).get(person)):
        p = as_mapping(raw)
        if name := _text(as_mapping(p.get(f"{person}-name")).get("name")):
            out.append(Party(name.strip().rstrip(","), p.get("@data-format") == "original"))
    return tuple(out)


def _texts(nodes: JsonValue) -> tuple[Text, ...]:
    out = []
    for raw in items(nodes):
        node = as_mapping(raw)
        paragraphs = [_text(p) for p in items(node.get("p"))] if "p" in node else [_text(node)]
        value = " ".join(p for p in paragraphs if p)
        if value:
            out.append(Text(as_str(node.get("@lang")), value))
    return tuple(out)


def _cpc(biblio: Mapping[str, JsonValue]) -> tuple[str, ...]:
    """Renvoie les codes CPC du membre (`G09F13/0436`)."""
    codes = []
    for raw in items(as_mapping(biblio.get("patent-classifications")).get("patent-classification")):
        c = as_mapping(raw)
        if not (as_str(as_mapping(c.get("classification-scheme")).get("@scheme")) or "").startswith(
            "CPC"
        ):
            continue
        parts = [
            _text(c.get(k)) or ""
            for k in ("section", "class", "subclass", "main-group", "subgroup")
        ]
        if all(parts):
            codes.append(f"{''.join(parts[:3])}{parts[3]}/{parts[4]}")
    return tuple(dict.fromkeys(codes))


def _member(raw: Mapping[str, JsonValue]) -> Member:
    document = as_mapping(raw.get("exchange-document"))
    biblio = as_mapping(document.get("bibliographic-data"))
    priorities = tuple(
        p
        for claim in items(raw.get("priority-claim"))
        if (p := _docdb(as_mapping(claim).get("document-id")))
    )
    return Member(
        publication=_docdb(as_mapping(raw.get("publication-reference")).get("document-id")),
        application=_docdb(as_mapping(raw.get("application-reference")).get("document-id")),
        priorities=priorities,
        titles=_texts(biblio.get("invention-title")),
        abstracts=_texts(document.get("abstract")),
        applicants=_parties(biblio, "applicants", "applicant"),
        inventors=_parties(biblio, "inventors", "inventor"),
        cpc=_cpc(biblio),
    )


def family_members(payload: Mapping[str, JsonValue]) -> list[Member]:
    """Renvoie les membres d'une famille, lus dans la réponse d'OPS (`ops:world-patent-data`) ou dans son contenu (`ops:patent-family`)."""
    family = (
        as_mapping(as_mapping(payload.get("ops:world-patent-data")).get("ops:patent-family"))
        or payload
    )
    return [_member(as_mapping(m)) for m in items(family.get("ops:family-member"))]


def filings(members: list[Member]) -> list[DocId]:
    """Renvoie les demandes de la famille, priorités comprises : une priorité jamais publiée est absente des membres."""
    return [d for m in members for d in (m.application, *m.priorities) if d]


def publications(members: list[Member]) -> list[DocId]:
    return [m.publication for m in members if m.publication]


def first_priority(members: list[Member]) -> DocId | None:
    """Renvoie la priorité la plus ancienne de la famille, à défaut la demande la plus ancienne."""
    dated = [p for m in members for p in m.priorities if p.date]
    if not dated:
        dated = [m.application for m in members if m.application and m.application.date]
    return min(dated, key=lambda d: (d.date, d.identifier)) if dated else None


def family_key(members: list[Member]) -> str | None:
    """Renvoie l'identifiant de la famille : le numéro de sa priorité la plus ancienne."""
    priority = first_priority(members)
    return priority.identifier if priority else None


def family_numbers(members: list[Member]) -> tuple[set[str], set[str]]:
    """Renvoie les numéros de publication et les numéros de demande de la famille, sans code de type."""
    return {d.identifier for d in publications(members)}, {d.identifier for d in filings(members)}


def applicant_forms(members: list[Member]) -> list[str]:
    """Renvoie les formes de comparaison des noms des déposants, tous formats confondus, sans doublon."""
    return list(dict.fromkeys(p.normalized for m in members for p in m.applicants if p.normalized))


def display_names(parties: list[Party]) -> list[str]:
    """Renvoie un nom par personne ou organisation : la graphie du format original, à défaut celle du format epodoc sans pays. La graphie « NOM, Prénom » est préférée."""
    chosen = [p for p in parties if p.original] or parties
    names: dict[str, str] = {}
    for p in chosen:
        name = _COUNTRY_SUFFIX_RE.sub("", p.name)
        key = p.normalized
        if key and (key not in names or ("," in name and "," not in names[key])):
            names[key] = name
    return list(names.values())
