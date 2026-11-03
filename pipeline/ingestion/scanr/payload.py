"""Lecture des payloads ScanR par la normalisation : affiliations feuilles, identifiants, concepts.

Les payloads sont les objets JSON bruts de l'API, sans schéma typé."""

import re
from collections.abc import Mapping

from domain.documents.identifiers import NNT
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.subjects.subject import SubjectLink, rameau_subject
from domain.types import JsonValue, as_mapping, as_sequence, as_str

# Types des concepts ScanR (`domains`). Les vedettes sudoc (RAMEAU) relèvent d'un vocabulaire contrôlé. Les concepts wikidata, détectés par ScanR dans le texte, et les mots-clés sont des mots-clés libres.
_RAMEAU_CONCEPT_TYPE = "sudoc"

_KEYWORD_CONCEPT_TYPES = frozenset({"wikidata", "keyword"})


def select_leaf_affiliations(
    affiliations: list[Mapping[str, JsonValue]],
) -> list[Mapping[str, JsonValue]]:
    """Renvoie les affiliations ScanR marquées laboratoire, à défaut toutes les affiliations.

    ScanR donne côte à côte l'affiliation au laboratoire (`id_name_author_labo` rempli, seule affichée sur ScanR) et les tutelles, déjà présentes parmi les tutelles des structures. Le laboratoire seul évite de compter deux fois les tutelles. Un auteur sans laboratoire identifié par ScanR garde toutes ses affiliations.
    """
    labo = [a for a in affiliations if a.get("id_name_author_labo")]
    return labo or affiliations


# Identifiant ScanR d'une thèse soutenue : `nnt<NNT>` ou `these<NNT>`, le NNT commençant par l'année de soutenance. Une thèse en préparation (`nnts<numéro>`) est sans NNT.
_THESIS_ID_RE = re.compile(r"^(?:nnt|these)(\d{4}[A-Za-z0-9]+)$")


def extract_nnt_from_scanr_id(scanr_id: str | None) -> str | None:
    """Renvoie le NNT d'un identifiant ScanR de thèse soutenue (`nnt2019clfad020` → `2019CLFAD020`), `None` pour tout autre identifiant."""
    match = _THESIS_ID_RE.match(scanr_id or "")
    nnt = NNT.try_parse(match.group(1)) if match else None
    return str(nnt) if nnt else None


# Préfixe d'un identifiant ScanR contenant l'identifiant d'un document d'une autre source, et type de cet identifiant.
_DERIVED_PREFIXES = (
    ("doi", SourceIdentifierType.DOI),
    ("hal", SourceIdentifierType.HAL_ID),
    ("pmid", SourceIdentifierType.PMID),
)


def scanr_derived_identifier(scanr_id: str) -> SourceIdentifier | None:
    """Renvoie l'identifiant dérivé d'un document ScanR, contenu dans son identifiant ScanR : `doi10.1/x`, `halhal-01234567`, `nnt2019clfad020`, `pmid28493063`."""
    if nnt := extract_nnt_from_scanr_id(scanr_id):
        return SourceIdentifier(SourceIdentifierType.NNT, nnt, SourceIdentifierRole.DERIVED)
    for prefix, id_type in _DERIVED_PREFIXES:
        if scanr_id.startswith(prefix):
            return SourceIdentifier(id_type, scanr_id[len(prefix) :], SourceIdentifierRole.DERIVED)
    return None


def scanr_concept_keywords(domains: JsonValue) -> list[str]:
    """Renvoie les libellés des concepts wikidata et des mots-clés de ScanR (`domains`), dédoublonnés sans tenir compte de la casse."""
    keywords: list[str] = []
    seen: set[str] = set()
    for entry in as_sequence(domains):
        concept = as_mapping(entry)
        if as_str(concept.get("type")) not in _KEYWORD_CONCEPT_TYPES:
            continue
        label = (as_str(as_mapping(concept.get("label")).get("default")) or "").strip()
        if label and label.lower() not in seen:
            seen.add(label.lower())
            keywords.append(label)
    return keywords


def scanr_subjects(domains: JsonValue) -> list[SubjectLink]:
    """Renvoie les vedettes RAMEAU de ScanR (`domains` de type `sudoc`), codées par leur PPN."""
    return [
        SubjectLink(subject)
        for entry in as_sequence(domains)
        if as_str((concept := as_mapping(entry)).get("type")) == _RAMEAU_CONCEPT_TYPE
        and (
            subject := rameau_subject(
                as_str(concept.get("code")), as_str(as_mapping(concept.get("label")).get("default"))
            )
        )
    ]
