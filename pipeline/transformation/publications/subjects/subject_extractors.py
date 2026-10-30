"""Extraction des libellés de concept par source, depuis le champ `topics` d'un enregistrement source.

Chaque source a son format de `topics`. Ces fonctions pures le réduisent à une liste de libellés. L'écriture des sujets et des liens est commune (`subject_ingestion`). Le registre `SUBJECT_EXTRACTORS` associe chaque source à sa fonction de lecture et à la langue de ses libellés. Une source absente du registre (Crossref : mots-clés libres seuls) produit zéro concept.
"""

from collections.abc import Callable

from domain.sources.hal import hal_domain_labels
from domain.types import JsonValue, as_mapping, as_str
from pipeline.transformation.publications.subjects.subject_cache import dedup_strs

# Niveaux OpenAlex, liés à plat : domain, field, subfield, topic.
_OPENALEX_LEVELS = ("domain", "field", "subfield", "topic")


def hal_labels(topics: JsonValue) -> list[str]:
    """Renvoie les domaines HAL (`{"hal_domains": [...]}`), chaque niveau du chemin à plat.

    Chaque entrée contient le code du domaine et le chemin de ses libellés, découpé par `hal_domain_labels`. Les niveaux sont liés à plat, comme les quatre niveaux OpenAlex.
    """
    if not isinstance(topics, dict):
        return []
    labels: list[str] = []
    for entry in dedup_strs(topics.get("hal_domains")):
        labels.extend(hal_domain_labels(entry))
    return labels


def openalex_labels(topics: JsonValue) -> list[str]:
    """Renvoie les topics OpenAlex (`[{domain, field, subfield, topic}, ...]`), les quatre niveaux à plat."""
    if not isinstance(topics, list):
        return []
    labels: list[str] = []
    for entry in topics:
        if not isinstance(entry, dict):
            continue
        for level in _OPENALEX_LEVELS:
            label = entry.get(level)
            if isinstance(label, str) and label.strip():
                labels.append(label.strip())
    return labels


def wos_labels(topics: JsonValue) -> list[str]:
    """Renvoie les sujets et vedettes WoS (`{"subjects": [...], "headings": [...]}`)."""
    if not isinstance(topics, dict):
        return []
    return dedup_strs(topics.get("subjects")) + dedup_strs(topics.get("headings"))


def scanr_labels(topics: JsonValue) -> list[str]:
    """Renvoie le libellé des vedettes Sudoc (RAMEAU) de ScanR (`[{"type": "sudoc", "code": …, "label": {"default": …}}, ...]`)."""
    if not isinstance(topics, list):
        return []
    return dedup_strs(
        [as_str(as_mapping(as_mapping(entry).get("label")).get("default")) for entry in topics]
    )


def theses_labels(topics: JsonValue) -> list[str]:
    """Renvoie la discipline et les vedettes RAMEAU de theses.fr (`{"discipline": str, "rameau": [...]}`)."""
    if not isinstance(topics, dict):
        return []
    labels: list[str] = []
    discipline = topics.get("discipline")
    if isinstance(discipline, str) and discipline.strip():
        labels.append(discipline.strip())
    return labels + dedup_strs(topics.get("rameau"))


SUBJECT_EXTRACTORS: dict[str, tuple[Callable[[JsonValue], list[str]], str | None]] = {
    "hal": (hal_labels, None),
    "openalex": (openalex_labels, "en"),
    "wos": (wos_labels, "en"),
    "scanr": (scanr_labels, None),
    "theses": (theses_labels, "fr"),
}
