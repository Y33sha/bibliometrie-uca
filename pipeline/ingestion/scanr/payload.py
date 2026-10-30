"""Lecture des payloads ScanR par la normalisation : affiliations feuilles, identifiants, concepts, statut open access.

Les payloads sont les objets JSON bruts de l'API, sans schéma typé."""

import re
from collections.abc import Mapping

from domain.publications.identifiers import NNT
from domain.source_records.identifiers import (
    SourceIdentifier,
    SourceIdentifierRole,
    SourceIdentifierType,
)
from domain.types import JsonValue, as_mapping, as_sequence, as_str

# Types des concepts ScanR (`domains`). Les vedettes sudoc (RAMEAU) relèvent d'un vocabulaire contrôlé. Les concepts wikidata, détectés par ScanR dans le texte, et les mots-clés sont des mots-clés libres.
_SUBJECT_CONCEPT_TYPES = frozenset({"sudoc"})

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


def split_scanr_concepts(domains: JsonValue) -> tuple[list[str], list[JsonValue]]:
    """Répartit les concepts ScanR (`domains`) en mots-clés libres et en sujets.

    Renvoie d'abord les libellés des concepts wikidata et des mots-clés, dédoublonnés sans tenir compte de la casse, puis les vedettes sudoc sous leur forme ScanR, avec leur code. Un concept d'un autre type est écarté.
    """
    keywords: list[str] = []
    seen: set[str] = set()
    subjects: list[JsonValue] = []
    for entry in as_sequence(domains):
        concept = as_mapping(entry)
        kind = as_str(concept.get("type"))
        if kind in _SUBJECT_CONCEPT_TYPES:
            subjects.append(entry)
        elif kind in _KEYWORD_CONCEPT_TYPES:
            label = (as_str(as_mapping(concept.get("label")).get("default")) or "").strip()
            if label and label.lower() not in seen:
                seen.add(label.lower())
                keywords.append(label)
    return keywords, subjects


def derive_scanr_oa_status(
    is_oa: bool | None, oa_evidence: Mapping[str, JsonValue] | None
) -> str | None:
    """Renvoie le statut open access d'un document ScanR, déduit de `isOa` et de `oaEvidence` (hôte et licence de la copie ouverte).

    - `isOa` absent → `None` : le statut vient des autres sources (`best_oa_status`) ;
    - `isOa` faux → `closed` ;
    - copie ouverte dans une archive (`repository`) → `green` ;
    - copie ouverte chez l'éditeur, sous licence Creative Commons → `hybrid`, changé en `gold` par `best_oa_status` si une autre source donne `gold` ;
    - copie ouverte chez l'éditeur, sans licence Creative Commons → `bronze` ;
    - hôte absent ou inconnu → `None`.
    """
    if is_oa is None:
        return None
    if not is_oa:
        return "closed"
    ev = as_mapping(oa_evidence)
    host_type = as_str(ev.get("hostType"))
    license_ = (as_str(ev.get("license")) or "").lower()
    if host_type == "repository":
        return "green"
    if host_type == "publisher":
        return "hybrid" if license_.startswith("cc-") else "bronze"
    return None
