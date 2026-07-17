"""Extraction des libellés de concept par source, depuis le champ `topics` d'une `source_publication`.

Chaque source expose ses concepts dans un format `topics` distinct ; ces fonctions pures le réduisent à une liste de libellés. L'upsert et la liaison sont communs (orchestrateur `ingestion`). Le registre `SUBJECT_EXTRACTORS` associe chaque source à son extracteur et à la langue de ses libellés ; une source absente (CrossRef : mots-clés libres seuls) ne produit aucun concept.
"""

from collections.abc import Callable

from application.pipeline.subjects._common import dedup_strs
from domain.sources.hal import hal_domain_labels
from domain.types import JsonValue

# Niveaux OpenAlex, liés à plat : domain, field, subfield, topic.
_OPENALEX_LEVELS = ("domain", "field", "subfield", "topic")


def hal_labels(topics: JsonValue) -> list[str]:
    """Domaines HAL (`{"hal_domains": [...]}`), chaque niveau du chemin à plat.

    Chaque entrée porte le code du domaine et le chemin de ses libellés, que `hal_domain_labels` découpe. Les niveaux sont liés à plat, comme les quatre niveaux OpenAlex.
    """
    if not isinstance(topics, dict):
        return []
    labels: list[str] = []
    for entry in dedup_strs(topics.get("hal_domains")):
        labels.extend(hal_domain_labels(entry))
    return labels


def openalex_labels(topics: JsonValue) -> list[str]:
    """Topics OpenAlex (`[{domain, field, subfield, topic}, ...]`), les 4 niveaux à plat."""
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
    """Sujets et vedettes WoS (`{"subjects": [...], "headings": [...]}`)."""
    if not isinstance(topics, dict):
        return []
    return dedup_strs(topics.get("subjects")) + dedup_strs(topics.get("headings"))


def scanr_labels(topics: JsonValue) -> list[str]:
    """Domaines ScanR : `topics` est soit une liste, soit un dict à clés `domains`/`topics`."""
    if isinstance(topics, list):
        return dedup_strs(topics)
    if isinstance(topics, dict):
        for key in ("domains", "topics"):
            value = topics.get(key)
            if isinstance(value, list):
                return dedup_strs(value)
    return []


def theses_labels(topics: JsonValue) -> list[str]:
    """Discipline + vedettes RAMEAU theses.fr (`{"discipline": str, "rameau": [...]}`)."""
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
