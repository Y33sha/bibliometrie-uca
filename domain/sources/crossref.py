"""Règles métier pures spécifiques à la source CrossRef.

Interprétation des champs propres au schéma CrossRef Works API — extracteurs et nettoyeurs qui encapsulent les conventions CrossRef pour le reste du pipeline.

Les `Mapping[str, JsonValue]` ici sont des payloads JSON bruts de l'API CrossRef (frontière dynamique avec une source externe, schéma non typé). Le `JsonValue` est délibéré : forcer `JsonValue` exigerait des `isinstance` partout sur le dict-walking interne, sans gain métier. Idem pour le retour de `extract_crossref_meta`, qui est un sous-ensemble destiné à `source_publications.meta` (JSONB).
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from domain.types import JsonValue, as_int, as_mapping, as_sequence, as_str

_JATS_TAG_RE = re.compile(r"</?jats:[A-Za-z][^<>]*>")


def strip_jats_tags(s: str) -> str:
    """Retire les balises XML JATS d'une chaîne.

    CrossRef stocke l'abstract en JATS XML (balises `<jats:p>`, `<jats:sec>`, etc.) ; on les retire pour exposer le texte brut.
    """
    return _JATS_TAG_RE.sub("", s)


def extract_crossref_pub_year(msg: Mapping[str, JsonValue], *, max_year: int) -> int | None:
    """Année de publication CrossRef, dans l'ordre `published > issued > published-online > published-print`.

    Sémantique CrossRef : `published` = min(published-online, published-print) ; `issued` = date déclarée par l'éditeur (peut être prospective sur des « futur numéro » 2030+ déposés avant publication réelle).

    Borne supérieure `max_year` (typiquement `current_year + 1` — un preprint daté de l'année suivante reste plausible). Au-dessus, on considère la donnée polluée et on retourne None ; le caller skippera la normalisation, et `refresh_from_sources` arbitrera depuis les autres sources. Borne inférieure 1500 (un DOI antérieur est manifestement aberrant).

    `max_year` est un paramètre injecté pour la testabilité (sinon couplage au calendrier réel rendrait les tests fragiles).
    """
    for field in ("published", "issued", "published-online", "published-print"):
        date_parts = as_sequence(as_mapping(msg.get(field)).get("date-parts"))
        if not date_parts:
            continue
        # `date-parts` porte une liste de dates, chacune décomposée en [année, mois, jour].
        premiere = as_sequence(date_parts[0])
        year = as_int(premiere[0]) if premiere else None
        if year is not None and 1500 <= year <= max_year:
            return year
    return None


def parse_crossref_issns(msg: Mapping[str, JsonValue]) -> tuple[str | None, str | None]:
    """Retourne `(issn_print, eissn)`.

    CrossRef expose deux formats : `issn-type` (objets typés `{"type": "electronic"|"print", "value": "..."}`, fiable quand présent) et `ISSN` (liste plate non typée, fallback). Si `issn-type` distingue clairement les deux, on les sépare ; sinon on prend le premier `ISSN` brut comme print et eissn reste None.
    """
    issn_print: str | None = None
    eissn: str | None = None
    for entree in as_sequence(msg.get("issn-type")):
        issn_obj = as_mapping(entree)
        t = as_str(issn_obj.get("type"))
        v = issn_obj.get("value")
        if not isinstance(v, str) or not v.strip():
            continue
        if t == "electronic" and not eissn:
            eissn = v.strip()
        elif t == "print" and not issn_print:
            issn_print = v.strip()
    if issn_print or eissn:
        return issn_print, eissn
    issns = msg.get("ISSN") or []
    if isinstance(issns, list) and issns:
        first = issns[0]
        if isinstance(first, str) and first.strip():
            return first.strip(), None
    return None, None


def extract_crossref_meta(msg: Mapping[str, JsonValue]) -> Mapping[str, JsonValue] | None:
    """Extrait les champs CrossRef-spécifiques à conserver en JSONB.

    Whitelist explicite : `license`, `funder`, `relation`, `references_count` (si > 0), `indexed.timestamp`. Décision métier « ces champs ont une valeur, les autres on jette » — évite d'embarquer la totalité du payload CrossRef et fige le contrat de la colonne `source_publications.meta`.

    Le sous-objet `meta->'relation'` est consommé par l'étape « relations » de l'ingestion des sujets.
    """
    meta: dict[str, JsonValue] = {}
    for key in ("license", "funder", "relation"):
        val = msg.get(key)
        if val:
            meta[key] = val
    refs_count = msg.get("references-count")
    if isinstance(refs_count, int) and refs_count > 0:
        meta["references_count"] = refs_count
    indexed = msg.get("indexed") or {}
    if isinstance(indexed, dict):
        ts = indexed.get("timestamp") or indexed.get("date-time")
        if ts:
            meta["indexed"] = ts
    return meta or None
