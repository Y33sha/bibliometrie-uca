"""Arbitrage entre communication sans texte publié (`conference`), résumé publié (`conference_abstract`), poster et texte publié dans des actes (`conference_paper`), sur l'ensemble des enregistrements sources d'une publication."""

import re

from domain.documents.doc_types import DocType
from domain.normalize import normalize_text
from domain.source_records.biblio import BiblioKey
from domain.source_records.source_extras import SourceExtra, declares_conference
from domain.source_records.source_record import SourceRecord
from domain.types import as_str, as_strs

_SUPPLANTED_BY_CONFERENCE = frozenset(
    {DocType.ARTICLE, DocType.CONFERENCE_PAPER, DocType.PREPRINT, DocType.CONFERENCE}
)
"""Types supplantés par une source désignant explicitement une communication ou un résumé : Crossref dépose un résumé en revue comme `journal-article` et un résumé de réunion comme `posted-content`."""

_SUPPLANTED_BY_POSTER = frozenset({DocType.CONFERENCE, DocType.CONFERENCE_ABSTRACT})
"""Types supplantés par un poster déclaré par une source."""

_ABSTRACTS = re.compile(r"\babstracts?\b|\bresumes\b")
"""Titre d'un recueil de résumés : « Book of abstracts », « Recueil des résumés », « Abstracts with programs »."""

_UNKNOWN_PUBLISHERS = frozenset({"s n", "sn", "sans nom", "unknown"})
"""Éditeur inconnu, en toutes lettres ou abrégé."""


def _hal_titles(source: SourceRecord) -> list[str]:
    """Renvoie le titre de la source et les collections associés par un enregistrement source HAL à une communication."""
    source_extras = source.source_extras or {}
    titles = as_strs(source_extras.get(SourceExtra.SERIES))
    if source_title := as_str(source_extras.get(SourceExtra.SOURCE_TITLE)):
        titles.append(source_title)
    return titles


def names_abstracts(source: SourceRecord) -> bool:
    """Vrai si l'enregistrement source HAL range la communication dans un recueil de résumés."""
    return source.source == "hal" and any(
        _ABSTRACTS.search(normalize_text(t)) for t in _hal_titles(source)
    )


def _hal_editorial_fields(source: SourceRecord) -> bool:
    """Vrai si l'enregistrement source HAL décrit une publication : indicateur « avec actes », plage de pages, éditeur, collection, ou titre de source distinct du congrès."""
    source_extras = source.source_extras or {}
    biblio = source.biblio or {}
    if source_extras.get(SourceExtra.PROCEEDINGS) is True:
        return True
    if biblio.get(BiblioKey.LAST_PAGE):
        return True
    publisher = normalize_text(as_str(biblio.get(BiblioKey.PUBLISHER)) or "")
    if publisher and publisher not in _UNKNOWN_PUBLISHERS:
        return True
    congress = normalize_text(source.container_title or "")
    return any(normalize_text(t) not in ("", congress) for t in _hal_titles(source))


def attests_publication(source: SourceRecord) -> bool:
    """Vrai si l'enregistrement source décrit un texte publié : DOI, revue, monographie, congrès déclaré par Crossref, ou champs éditoriaux d'un enregistrement source HAL. Un dépôt HAL réduit à des annexes (diaporama, résumé) désigne une communication : ses champs éditoriaux comptent pour rien."""
    if source.dois.all or source.serial_id or source.monograph_id:
        return True
    if declares_conference(source.source_extras):
        return True
    return (
        source.source == "hal"
        and not (source.source_extras or {}).get(SourceExtra.ANNEX_DEPOSIT)
        and _hal_editorial_fields(source)
    )


def arbitrate_conference(doc_type: str, sources: list[SourceRecord]) -> str:
    """Arbitre le type d'une publication issue d'un congrès.

    Un enregistrement source qui désigne un résumé (`conference_abstract`, recueil de résumés HAL) l'emporte sur `article`, `conference_paper`, `preprint` et `conference`. À défaut, un enregistrement source `conference` l'emporte sur les trois premiers. Une `conference_paper` sans enregistrement source qui décrive un texte publié devient une `conference`. Un poster déclaré par une source l'emporte ensuite sur la communication et le résumé.
    """
    doc_type = _arbitrate_communication(doc_type, sources)
    if doc_type in _SUPPLANTED_BY_POSTER and any(s.doc_type == DocType.POSTER for s in sources):
        return DocType.POSTER
    return doc_type


def _arbitrate_communication(doc_type: str, sources: list[SourceRecord]) -> str:
    """Arbitre entre texte publié, résumé et communication (`arbitrate_conference`)."""
    if doc_type in _SUPPLANTED_BY_CONFERENCE:
        if any(s.doc_type == DocType.CONFERENCE_ABSTRACT or names_abstracts(s) for s in sources):
            return DocType.CONFERENCE_ABSTRACT
        if any(s.doc_type == DocType.CONFERENCE for s in sources):
            return DocType.CONFERENCE
    if doc_type == DocType.CONFERENCE_PAPER and not any(attests_publication(s) for s in sources):
        return DocType.CONFERENCE
    return doc_type
