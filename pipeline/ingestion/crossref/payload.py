"""Lecture des enregistrements sources Crossref par la normalisation.

Interprétation des champs propres au schéma CrossRef Works API — fonctions de lecture et nettoyeurs qui encapsulent les conventions CrossRef.

Les `Mapping[str, JsonValue]` ici sont des payloads JSON bruts de l'API CrossRef (frontière dynamique avec une source externe, schéma non typé). Le `JsonValue` est délibéré : forcer `JsonValue` exigerait des `isinstance` partout sur le dict-walking interne, sans gain métier. Idem pour le retour de `extract_crossref_meta`, qui est un sous-ensemble destiné à `source_records.source_extras` (JSONB).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from domain.serials.issns import IssnSupport, SerialIssn, received_issns
from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str, as_strs

_JATS_TAG_RE = re.compile(r"</?jats:[A-Za-z][^<>]*>")


def strip_jats_tags(s: str) -> str:
    """Retire les balises XML JATS d'une chaîne.

    CrossRef stocke l'abstract en JATS XML (balises `<jats:p>`, `<jats:sec>`, etc.) ; on les retire pour exposer le texte brut.
    """
    return _JATS_TAG_RE.sub("", s)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _is_tex_formula(line: str) -> bool:
    """La ligne est une formule LaTeX `$$…$$` seule."""
    stripped = line.strip()
    return len(stripped) > 4 and stripped.startswith("$$") and stripped.endswith("$$")


def _flattened_mathml(line: str, depth: int) -> bool:
    """Ligne vide, ou symbole isolé plus indenté que la formule."""
    stripped = line.strip()
    return not stripped or (len(stripped.split()) == 1 and _indent(line) > depth)


def clean_crossref_title(title: str) -> str:
    """Titre Crossref sans la version MathML de ses formules, espacement réduit à un espace simple.

    Un éditeur dépose chaque formule d'un titre en deux versions : LaTeX (`$$…$$`) et MathML. Crossref rend le titre avec l'indentation du XML déposé et sans les balises MathML : la formule LaTeX occupe une ligne, et chaque symbole MathML une ligne plus indentée qu'elle, avant ou après. Ces lignes de symboles isolés sont retirées. L'interface affiche la formule LaTeX.
    """
    lines = title.split("\n")
    dropped: set[int] = set()
    for i, line in enumerate(lines):
        if not _is_tex_formula(line):
            continue
        # Une formule en début de ligne n'a pas d'indentation : la ligne suivante porte celle du bloc.
        depth = _indent(line) or (_indent(lines[i + 1]) if i + 1 < len(lines) else 0)
        for step in (1, -1):
            j = i + step
            while (
                0 <= j < len(lines)
                and not _is_tex_formula(lines[j])
                and _flattened_mathml(lines[j], depth)
            ):
                dropped.add(j)
                j += step
    return " ".join(" ".join(line for k, line in enumerate(lines) if k not in dropped).split())


def extract_crossref_publication_year(msg: Mapping[str, JsonValue], *, max_year: int) -> int | None:
    """Année de publication CrossRef, dans l'ordre `published > issued > published-online > published-print > approved`.

    Sémantique CrossRef : `published` = min(published-online, published-print) ; `issued` = date déclarée par l'éditeur (peut être prospective sur des « futur numéro » 2030+ déposés avant publication réelle) ; `approved` = date de soutenance d'une thèse, seule date des thèses déposées par l'ABES.

    Borne supérieure `max_year` (typiquement `current_year + 1` — un preprint daté de l'année suivante reste plausible). Au-dessus, on considère la donnée polluée et on retourne None ; le caller skippera la normalisation, et `refresh_from_sources` arbitrera depuis les autres sources. Borne inférieure 1500 (un DOI antérieur est manifestement aberrant).

    `max_year` est un paramètre injecté pour la testabilité (sinon couplage au calendrier réel rendrait les tests fragiles).
    """
    for field in ("published", "issued", "published-online", "published-print", "approved"):
        date_parts = as_sequence(as_mapping(msg.get(field)).get("date-parts"))
        if not date_parts:
            continue
        # `date-parts` porte une liste de dates, chacune décomposée en [année, mois, jour].
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
    """Retourne `(issn_print, eissn)` : le premier ISSN de chaque support, ou à défaut le premier ISSN de support inconnu comme ISSN papier."""
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
    """Extrait les champs CrossRef-spécifiques à conserver en JSONB.

    Whitelist explicite : `license`, `funder`, `relation`, `conference` (nom et acronyme du congrès), `references_count` (si > 0), `indexed.timestamp`. Décision métier « ces champs ont une valeur, les autres on jette » — évite d'embarquer la totalité du payload CrossRef et fige le contrat de la colonne `source_records.source_extras`.

    Le sous-objet `source_extras->'relation'` est consommé par l'étape « relations » de l'ingestion des sujets.
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
