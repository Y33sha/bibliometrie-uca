"""
Mapping unifié des doc_types sources → enum canonique doc_type.

Chaque source (HAL, OpenAlex, WoS, ScanR, theses.fr) utilise sa propre
nomenclature. Ce module fournit un point unique de conversion vers l'enum
PostgreSQL `doc_type` de la table `publications`.

Usage :
    from domain.source_publications.doc_types import map_doc_type
    canonical = map_doc_type("THESE", source="hal")       # → "thesis"
    canonical = map_doc_type("dissertation", source="openalex")  # → "thesis"
    canonical = map_doc_type("article")                    # → "article" (lookup global)
"""

from typing import Literal

DocType = Literal[
    "article",
    "conference_paper",
    "book",
    "book_chapter",
    "thesis",
    "ongoing_thesis",
    "preprint",
    "review",
    "editorial",
    "report",
    "peer_review",
    "other",
    "dataset",
    "software",
    "patent",
    "hdr",
    "memoir",
    "poster",
    "letter",
    "erratum",
    "retraction",
    "book_review",
    "data_paper",
    "proceedings",
    "media",
]
DOC_TYPES: tuple[DocType, ...] = (
    "article",
    "conference_paper",
    "book",
    "book_chapter",
    "thesis",
    "ongoing_thesis",
    "preprint",
    "review",
    "editorial",
    "report",
    "peer_review",
    "other",
    "dataset",
    "software",
    "patent",
    "hdr",
    "memoir",
    "poster",
    "letter",
    "erratum",
    "retraction",
    "book_review",
    "data_paper",
    "proceedings",
    "media",
)
DOC_TYPES_SET: frozenset[str] = frozenset(DOC_TYPES)

# Mapping par source. Clés en minuscules pour le lookup.
# Les valeurs sont des valeurs valides de l'enum doc_type.
_SOURCE_MAPS: dict[str, dict[str, str]] = {
    "hal": {
        # Combinaisons type_sous-type (prioritaires)
        "art_artrev": "review",
        "art_bookreview": "book_review",
        "art_datapaper": "data_paper",
        "undefined_preprint": "preprint",
        "undefined_workingpaper": "preprint",
        "creport_resreport": "report",
        "report_resreport": "report",
        "report_dmp": "report",
        "report_expertreport": "report",
        "report_fundreport": "report",
        "report_techreport": "report",
        # Types simples
        "art": "article",
        "comm": "conference_paper",
        "poster": "poster",
        "ouv": "book",
        "ouv_crit": "book",
        "ouv_dictionary": "book",
        "ouv_manual": "book",
        "ouv_syntouv": "book",
        "couv": "book_chapter",
        "douv": "book_chapter",
        "these": "thesis",
        "hdr": "hdr",
        "preprint": "preprint",
        "prepublication": "preprint",
        "undefined": "other",
        "other": "other",
        "report": "report",
        "creport": "report",
        "mem": "memoir",
        "lecture": "other",
        "img": "other",
        "img_photography": "other",
        "video": "other",
        "son": "other",
        "map": "other",
        "software": "software",
        "patent": "patent",
        "note": "other",
        "blog": "other",
        "notice": "other",
        "issue": "other",
        "proceedings": "conference_paper",
        "trad": "other",
        "reference-entry": "other",
    },
    "openalex": {
        "article": "article",
        "review": "review",
        "book": "book",
        "book-chapter": "book_chapter",
        "proceedings-article": "conference_paper",
        "posted-content": "preprint",
        "preprint": "preprint",
        "dissertation": "thesis",
        "editorial": "editorial",
        "report": "report",
        "letter": "letter",
        "retraction": "retraction",
        "erratum": "erratum",
        "paratext": "other",
        "peer-review": "peer_review",
        "standard": "other",
        "dataset": "dataset",
        "grant": "other",
        "supplementary-materials": "other",
        "software": "software",
        "other": "other",
    },
    "wos": {
        "article": "article",
        "review": "review",
        "book": "book",
        "book chapter": "book_chapter",
        "proceedings paper": "conference_paper",
        "editorial material": "editorial",
        "letter": "letter",
        "meeting abstract": "conference_paper",
        "book review": "book_review",
        "correction": "erratum",
        "retraction": "retraction",
        "news item": "media",
        "reprint": "other",
        "note": "other",
        "data paper": "data_paper",
        "early access": "article",
        "software review": "other",
        "discussion": "other",
        "biographical-item": "other",
        "bibliography": "other",
        "art exhibit review": "other",
        "dance performance review": "other",
        "film review": "other",
        "music performance review": "other",
        "music score review": "other",
        "poetry": "other",
        "record review": "other",
        "theater review": "other",
        "tv review, radio review": "other",
        "hardware review": "other",
        "database review": "other",
        "chronology": "other",
        "excerpt": "other",
        "fiction, creative prose": "other",
        "script": "other",
        "item about an individual": "other",
    },
    "scanr": {
        "journal-article": "article",
        "book-chapter": "book_chapter",
        "book": "book",
        "proceedings": "conference_paper",
        "thesis": "thesis",
        "ongoing_thesis": "ongoing_thesis",
        "hdr": "hdr",
        "preprint": "preprint",
        "other": "other",
    },
    "theses": {
        "thesis": "thesis",
        "ongoing_thesis": "ongoing_thesis",
    },
    "datacite": {
        # resourceTypeGeneral (vocabulaire contrôlé DataCite)
        "journalarticle": "article",
        "preprint": "preprint",
        "conferencepaper": "conference_paper",
        "conferenceproceeding": "proceedings",
        "book": "book",
        "bookchapter": "book_chapter",
        "dissertation": "thesis",
        "report": "report",
        "poster": "poster",
        "dataset": "dataset",
        "datapaper": "data_paper",
        "software": "software",
        "computationalnotebook": "software",
        "peerreview": "peer_review",
        "audiovisual": "media",
        "image": "other",
        "collection": "other",
        "physicalobject": "other",
        "sound": "other",
        "model": "other",
        "workflow": "other",
        "standard": "other",
        "event": "other",
        "service": "other",
        "instrument": "other",
        "text": "other",
        "other": "other",
        # resourceType (texte libre, valeurs réelles observées sur le corpus UCA)
        "journal article": "article",
        "journal contribution": "article",
        "article": "article",
        "working paper": "preprint",
        "book chapter": "book_chapter",
        "conference paper": "conference_paper",
        "conference proceeding": "proceedings",
        "thesis": "thesis",
        "project deliverable": "report",
        "figure": "other",
        "taxonomic treatment": "other",
        "post": "other",
    },
    "crossref": {
        "journal-article": "article",
        "book-chapter": "book_chapter",
        "book": "book",
        "monograph": "book",
        "edited-book": "book",
        "reference-book": "book",
        "reference-entry": "other",
        "dissertation": "thesis",
        "proceedings-article": "conference_paper",
        "proceedings": "proceedings",
        "posted-content": "preprint",
        "preprint": "preprint",
        "peer-review": "peer_review",
        "report": "report",
        "report-component": "report",
        "dataset": "dataset",
        "journal-issue": "other",
        "component": "other",
        "grant": "other",
        "standard": "other",
        "other": "other",
    },
}

# Sous-types qui priment sur "article" générique : si une source prioritaire
# (typiquement CrossRef avec "journal-article") dit "article", mais qu'une
# source moins prioritaire (HAL, OA…) reconnaît un sous-type plus précis,
# on préfère le sous-type pour ne pas perdre l'information.
#
# CrossRef ne distingue pas ces sous-types (tout est "journal-article") ;
# HAL fait la distinction via ses combinaisons type_sous-type
# ("art_artrev" → "review", "art_bookreview" → "book_review", etc.).
# Cette logique d'arbitrage vit dans `application.publications._first_doc_type`.
ARTICLE_SUBTYPES: frozenset[str] = frozenset(
    {
        "review",
        "book_review",
        "data_paper",
        "conference_paper",
        "editorial",
        "letter",
        "erratum",
        "retraction",
    }
)


def map_doc_type(raw: str | None, source: str | None = None) -> str:
    """Convertit un doc_type source en valeur canonique de l'enum doc_type.

    Gère les types composites séparés par ";" (ex: WoS "Article; Proceedings Paper")
    en prenant le premier type significatif (non "other").

    Lookup :
    1. Si source est fourni, cherche dans le mapping de cette source.
    2. Sinon (ou si non trouvé), cherche dans tous les mappings.
    3. Si la valeur est déjà un doc_type valide, la retourne telle quelle.
    4. Sinon retourne "other".
    """
    if not raw:
        return "other"

    # Types composites (WoS) : "Article; Proceedings Paper"
    if ";" in raw:
        parts = [p.strip() for p in raw.split(";") if p.strip()]
        best = "other"
        for part in parts:
            mapped = map_doc_type(part, source)
            if mapped != "other":
                return mapped
            best = mapped
        return best

    key = raw.strip().lower()

    # 1. Lookup dans la source spécifique
    if source:
        source_map = _SOURCE_MAPS.get(source)
        if source_map:
            result = source_map.get(key)
            if result:
                return result

    # 2. Lookup global (toutes les sources)
    for smap in _SOURCE_MAPS.values():
        result = smap.get(key)
        if result:
            return result

    # 3. Identity si déjà valide
    if key in DOC_TYPES_SET:
        return key

    return "other"
