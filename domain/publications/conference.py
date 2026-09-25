"""Communication (`conference`) ou texte publié dans des actes (`conference_paper`).

Une `conference_paper` est un texte publié dans des actes. Une `conference` est une communication sans texte publié, résumés compris. La décision se prend sur l'ensemble des enregistrements d'une publication : un enregistrement suffit à attester la publication, un autre peut la désigner comme résumé.
"""

import re

from domain.normalize import normalize_text
from domain.publications.doc_types import DocType
from domain.source_publications.source_publication import SourcePublication
from domain.types import as_str, as_strs

# Types qu'une source désignant explicitement une communication supplante : Crossref dépose un résumé en revue comme `journal-article` et un résumé de réunion comme `posted-content`.
_SUPPLANTED_BY_CONFERENCE = frozenset(
    {DocType.ARTICLE, DocType.CONFERENCE_PAPER, DocType.PREPRINT, DocType.CONFERENCE}
)

# Titre d'un recueil de résumés : « Book of abstracts », « Recueil des résumés », « Abstracts with programs ».
_ABSTRACTS = re.compile(r"\babstracts?\b|\bresumes\b")

# Plage de pages (« 229-251 », « pp. 465-470 ») : un décompte (« 21 p. ») ou « np » n'atteste pas un texte publié.
_PAGE_RANGE = re.compile(r"\d+\s*[-–]\s*\d+")

# Éditeur inconnu, en toutes lettres ou abrégé.
_UNKNOWN_PUBLISHERS = frozenset({"s n", "sn", "sans nom", "unknown"})


def _hal_titles(source: SourcePublication) -> list[str]:
    """Titre de la source et collections qu'une notice HAL associe à une communication."""
    meta = source.meta or {}
    titles = as_strs(meta.get("series"))
    if source_title := as_str(meta.get("source_title")):
        titles.append(source_title)
    return titles


def names_abstracts(source: SourcePublication) -> bool:
    """La notice HAL range la communication dans un recueil de résumés."""
    return source.source == "hal" and any(
        _ABSTRACTS.search(normalize_text(t)) for t in _hal_titles(source)
    )


def _hal_editorial_fields(source: SourcePublication) -> bool:
    """La notice HAL décrit une publication : indicateur « avec actes », plage de pages, éditeur, collection, ou titre de source distinct du congrès."""
    meta = source.meta or {}
    biblio = source.biblio or {}
    if meta.get("proceedings") is True:
        return True
    if _PAGE_RANGE.search(as_str(biblio.get("pages")) or ""):
        return True
    publisher = normalize_text(as_str(biblio.get("publisher")) or "")
    if publisher and publisher not in _UNKNOWN_PUBLISHERS:
        return True
    congress = normalize_text(source.container_title or "")
    return any(normalize_text(t) not in ("", congress) for t in _hal_titles(source))


def attests_publication(source: SourcePublication) -> bool:
    """L'enregistrement atteste un texte publié : DOI, revue, monographie, congrès déclaré par Crossref, ou champs éditoriaux d'une notice HAL."""
    if source.doi or source.journal_id or source.monograph_id:
        return True
    if (source.meta or {}).get("conference"):
        return True
    return source.source == "hal" and _hal_editorial_fields(source)


def arbitrate_conference(doc_type: str, sources: list[SourcePublication]) -> str:
    """Type d'une publication qui relève d'un congrès, au vu de tous ses enregistrements.

    Un enregistrement qui désigne une communication (`conference`, recueil de résumés HAL) l'emporte sur `article`, `conference_paper` et `preprint`. Une `conference_paper` qu'aucun enregistrement n'atteste devient une `conference`. Les autres types restent inchangés.
    """
    if doc_type in _SUPPLANTED_BY_CONFERENCE and any(
        s.doc_type == DocType.CONFERENCE or names_abstracts(s) for s in sources
    ):
        return DocType.CONFERENCE
    if doc_type == DocType.CONFERENCE_PAPER and not any(attests_publication(s) for s in sources):
        return DocType.CONFERENCE
    return doc_type
