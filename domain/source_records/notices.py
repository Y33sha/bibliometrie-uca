"""Avis (errata, avis de rétractation) : signaux propres à un enregistrement source.

- Crossref déclare les mises à jour d'une œuvre (`update-to`, `updated-by`), avec leur type.
- Le titre WoS d'un erratum est le titre de l'article corrigé, suivi de sa référence.
"""

import re
from collections.abc import Iterable, Mapping
from typing import NamedTuple

from domain.documents.doc_types import DocType
from domain.source_records.source_extras import SourceExtra
from domain.types import JsonValue, as_mapping, as_sequence, as_str

CROSSREF_CORRECTION_UPDATES = frozenset({"correction", "erratum", "corrigendum", "addendum"})
"""Types de mise à jour Crossref d'une correction. `clarification` relie un commentaire et sa réponse (Royal Society of Chemistry) : il reste hors des corrections."""

CROSSREF_RETRACTION_UPDATE = "retraction"
"""Type de mise à jour Crossref d'un avis de rétractation. Vers le DOI de l'enregistrement source lui-même, il signale une rétractation sur place."""

CROSSREF_WITHDRAWAL_UPDATE = "withdrawal"
"""Type de mise à jour Crossref d'un retrait. Elsevier le déclare sur l'enregistrement source retiré, doublon accidentel d'un article déjà publié, vers cet article."""

CROSSREF_CONCERN_UPDATE = "expression_of_concern"
"""Type de mise à jour Crossref d'un avis de préoccupation de l'éditeur."""

_NOTICE_UPDATES = CROSSREF_CORRECTION_UPDATES | {CROSSREF_RETRACTION_UPDATE}
"""Types de mise à jour d'un erratum ou d'un avis de rétractation."""


def _single_updated_doi(
    source_extras: Mapping[str, JsonValue] | None, own_doi: str, update_types: Iterable[str]
) -> str | None:
    """Renvoie le DOI visé par les mises à jour Crossref de ces types déclarées dans `update-to`, hors `own_doi`. `None` sans déclaration, ou pour plusieurs DOI visés."""
    types = frozenset(update_types)
    declared = {
        doi
        for entry in as_sequence((source_extras or {}).get(SourceExtra.UPDATE_TO))
        if (as_str(as_mapping(entry).get("type")) or "") in types
        and (doi := as_str(as_mapping(entry).get("doi")))
        and doi != own_doi
    }
    return next(iter(declared)) if len(declared) == 1 else None


def corrected_work_doi(source_extras: Mapping[str, JsonValue] | None, own_doi: str) -> str | None:
    """Renvoie le DOI de l'œuvre corrigée ou rétractée, déclaré par un avis Crossref dans `update-to`. `None` sans déclaration, ou pour plusieurs œuvres déclarées."""
    return _single_updated_doi(source_extras, own_doi, _NOTICE_UPDATES)


def withdrawn_original_doi(
    source_extras: Mapping[str, JsonValue] | None, own_doi: str
) -> str | None:
    """Renvoie le DOI de l'article original, déclaré par l'enregistrement source Crossref d'un doublon retiré : retrait (`withdrawal`) dans `update-to`, vers un autre DOI. `None` sans déclaration, ou pour plusieurs DOI déclarés."""
    return _single_updated_doi(source_extras, own_doi, {CROSSREF_WITHDRAWAL_UPDATE})


def notice_doc_type(update_types: Iterable[str]) -> DocType | None:
    """Renvoie le type de document d'un enregistrement source qui déclare ces mises à jour vers une autre œuvre : `retraction` pour une rétractation, `erratum` pour une correction, `None` sinon."""
    types = frozenset(update_types)
    if CROSSREF_RETRACTION_UPDATE in types:
        return DocType.RETRACTION
    if types & CROSSREF_CORRECTION_UPDATES:
        return DocType.ERRATUM
    return None


_WOS_ERRATUM_REFERENCE = re.compile(r"\s*\(vol\.?\s+[^()]*?\b(\d{4})\s*\)\s*$", re.IGNORECASE)
"""Référence de l'article corrigé en fin de titre d'un erratum WoS : `(vol 22, pg 385, 2020)`, `(vol 845, 138110, 2023)`. Le dernier nombre est l'année de l'article."""


class CorrectedArticle(NamedTuple):
    """Article corrigé, désigné par le titre d'un erratum WoS."""

    title: str
    year: int


def wos_corrected_article(erratum_title: str) -> CorrectedArticle | None:
    """Renvoie le titre et l'année de l'article corrigé, lus dans le titre d'un erratum WoS : titre de l'article suivi de sa référence. `None` sans référence."""
    match = _WOS_ERRATUM_REFERENCE.search(erratum_title)
    if match is None or not (title := erratum_title[: match.start()].strip()):
        return None
    return CorrectedArticle(title, int(match.group(1)))
