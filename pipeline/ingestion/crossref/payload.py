"""Lecture des enregistrements sources Crossref par la normalisation : conventions des champs de l'API Works.

Les payloads sont les objets JSON bruts de l'API, sans schéma typé.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from domain.serials.issns import IssnSupport, SerialIssn, received_issns
from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, as_strs

_JATS_TAG_RE = re.compile(r"</?jats:[A-Za-z][^<>]*>")


def strip_jats_tags(s: str) -> str:
    """Retire les balises JATS d'une chaîne : Crossref donne le résumé en XML JATS (`<jats:p>`, `<jats:sec>`…)."""
    return _JATS_TAG_RE.sub("", s)


def extract_crossref_publication_year(msg: Mapping[str, JsonValue], *, max_year: int) -> int | None:
    """Année de publication Crossref : la première année plausible parmi `published`, `issued`, `published-online`, `published-print` et `approved`.

    `published` est la plus ancienne des dates en ligne et papier. `issued` est la date que déclare l'éditeur ; elle peut viser un numéro futur, déposé avant parution. `approved` est la date de soutenance d'une thèse, seule date des thèses déposées par l'ABES.

    Une année plausible tient entre 1500 et `max_year`, en général l'année suivante : un preprint peut être daté de l'année à venir. Sans année plausible, la normalisation refuse l'enregistrement, et les autres sources donnent l'année de la publication. `max_year` est un paramètre pour que les tests restent indépendants du calendrier.
    """
    for field in ("published", "issued", "published-online", "published-print", "approved"):
        date_parts = as_sequence(as_mapping(msg.get(field)).get("date-parts"))
        if not date_parts:
            continue
        # `date-parts` contient une liste de dates, chacune décomposée en [année, mois, jour].
        first = as_sequence(date_parts[0])
        year = as_int(first[0]) if first else None
        if year is not None and 1500 <= year <= max_year:
            return year
    return None


_ISSN_SUPPORTS = {"print": IssnSupport.PRINT, "electronic": IssnSupport.ELECTRONIC}


def crossref_issns(msg: Mapping[str, JsonValue]) -> tuple[SerialIssn, ...]:
    """ISSN d'un enregistrement source Crossref. `issn-type` donne le support (papier ou en ligne) ; un ISSN de la liste `ISSN` absent de `issn-type` a un support inconnu."""
    typed = []
    for entry in as_sequence(msg.get("issn-type")):
        issn_obj = as_mapping(entry)
        support = _ISSN_SUPPORTS.get(as_str(issn_obj.get("type")) or "")
        value = as_str(issn_obj.get("value"))
        if support is not None and value:
            typed.append(SerialIssn(issn=value, support=support))
    plain = [SerialIssn(issn=value) for value in as_strs(msg.get("ISSN"))]
    return received_issns([*typed, *plain])


def parse_crossref_issns(msg: Mapping[str, JsonValue]) -> tuple[str | None, str | None]:
    """ISSN papier et électronique : le premier de chaque support, à défaut le premier ISSN de support inconnu comme ISSN papier."""
    issns = crossref_issns(msg)

    def first(support: IssnSupport | None) -> str | None:
        return next((r.issn for r in issns if r.support is support), None)

    issn_print, eissn = first(IssnSupport.PRINT), first(IssnSupport.ELECTRONIC)
    if issn_print or eissn:
        return issn_print, eissn
    return first(None), None


def crossref_raw_doc_type(msg: Mapping[str, JsonValue]) -> str | None:
    """Type brut d'un document Crossref, suivi de son sous-type quand Crossref en donne un (`posted-content_preprint`, `posted-content_other`)."""
    doc_type = as_str(msg.get("type"))
    subtype = as_str(msg.get("subtype"))
    return f"{doc_type}_{subtype}" if doc_type and subtype else doc_type


def extract_crossref_conference(msg: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    """Nom et acronyme du congrès dont le document est issu, ou `None`.

    Crossref décrit le congrès dans `event` pour un `proceedings-article`. Springer le décrit dans les `assertion` du groupe `ConferenceInfo` pour un `book-chapter`.
    """

    def text(value: JsonValue) -> str | None:
        return (as_str(value) or "").strip() or None

    event = as_mapping(msg.get("event"))
    name = text(event.get("name"))
    acronym = text(event.get("acronym"))
    for entry in as_sequence(msg.get("assertion")):
        assertion = as_mapping(entry)
        if as_mapping(assertion.get("group")).get("name") != "ConferenceInfo":
            continue
        if assertion.get("name") == "conference_name":
            name = name or text(assertion.get("value"))
        elif assertion.get("name") == "conference_acronym":
            acronym = acronym or text(assertion.get("value"))
    if not name:
        return None
    conference: dict[str, JsonValue] = {"name": name}
    if acronym:
        conference["acronym"] = acronym
    return conference


def extract_crossref_source_extras(msg: Mapping[str, JsonValue]) -> Mapping[str, JsonValue] | None:
    """Champs propres à Crossref gardés dans `source_records.source_extras` : licence, financeurs, relations, congrès, titre de groupe d'un `posted-content`, nombre de références s'il est positif, date d'indexation. Le reste du payload est écarté.

    Les relations servent à la phase `relations`.
    """
    source_extras: dict[str, JsonValue] = {}
    for key in (SourceExtra.LICENSE, SourceExtra.FUNDER, SourceExtra.RELATION):
        val = msg.get(key)
        if val:
            source_extras[key] = val
    conference = extract_crossref_conference(msg)
    if conference:
        source_extras[SourceExtra.CONFERENCE] = conference
    if msg.get("type") == "posted-content" and (group_title := as_str(msg.get("group-title"))):
        source_extras[SourceExtra.GROUP_TITLE] = group_title
    refs_count = msg.get("references-count")
    if isinstance(refs_count, int) and refs_count > 0:
        source_extras[SourceExtra.REFERENCES_COUNT] = refs_count
    indexed = msg.get("indexed") or {}
    if isinstance(indexed, dict):
        ts = indexed.get("timestamp") or indexed.get("date-time")
        if ts:
            source_extras[SourceExtra.INDEXED] = ts
    return source_extras or None
