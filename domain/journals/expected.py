"""Mappings d'attendus pour la détection d'incohérences journal ↔ publication.

Deux règles métier déclaratives, consommées par le dashboard journal (`/api/journals/{id}/dashboard`) pour mettre en évidence les publications qui sortent du cadre annoncé par leur revue :

- `EXPECTED_OA_STATUSES_BY_OA_MODEL` : pour un `journals.oa_model` donné, quels `publications.oa_status` sont attendus.
- `EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE` : pour un `journals.journal_type` donné, quels `publications.doc_type` sont attendus.

Quand un signal manque (oa_model / oa_status / journal_type / doc_type à NULL ou `unknown`), la cohérence est réputée vraie : un signal absent ne compte pas comme une incohérence.
"""

from __future__ import annotations

EXPECTED_OA_STATUSES_BY_OA_MODEL: dict[str, frozenset[str]] = {
    "subscription": frozenset({"closed", "green", "hybrid", "bronze"}),
    "full_oa": frozenset({"gold", "diamond", "green"}),
    "repository": frozenset({"green"}),
}

EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE: dict[str, frozenset[str]] = {
    "journal": frozenset(
        {
            "article",
            "review",
            "editorial",
            "erratum",
            "letter",
            "retraction",
            "peer_review",
            "other",
        }
    ),
    "proceedings": frozenset({"conference_paper", "other"}),
    "book_series": frozenset({"book", "book_chapter", "other"}),
    "ebook_platform": frozenset({"book", "book_chapter", "other"}),
    "preprint_server": frozenset({"preprint", "other"}),
    "repository": frozenset(
        {
            # Repositories acceptent ~tout : pas de notion d'inattendu fort.
            "article",
            "review",
            "preprint",
            "thesis",
            "ongoing_thesis",
            "hdr",
            "memoir",
            "book",
            "book_chapter",
            "report",
            "dataset",
            "software",
            "patent",
            "poster",
            "letter",
            "erratum",
            "retraction",
            "editorial",
            "peer_review",
            "conference_paper",
            "other",
        }
    ),
    "media": frozenset({"media", "editorial", "other"}),
}


def is_oa_status_expected(oa_model: str | None, oa_status: str | None) -> bool:
    """Vrai si l'`oa_status` d'une publication est cohérent avec l'`oa_model` de sa revue.

    Vrai aussi quand un signal manque (`oa_model` NULL, `oa_status` NULL ou `unknown`, `oa_model` absent de la map) : cohérence réputée vraie.
    """
    if not oa_model or not oa_status or oa_status == "unknown":
        return True
    expected = EXPECTED_OA_STATUSES_BY_OA_MODEL.get(oa_model)
    if expected is None:
        return True
    return oa_status in expected


def is_doc_type_expected(journal_type: str | None, doc_type: str | None) -> bool:
    """Vrai si le `doc_type` d'une publication est cohérent avec le `journal_type` de sa revue.

    Vrai aussi quand un signal manque (`journal_type` NULL, `doc_type` NULL, `journal_type` absent de la map).
    """
    if not journal_type or not doc_type:
        return True
    expected = EXPECTED_DOC_TYPES_BY_JOURNAL_TYPE.get(journal_type)
    if expected is None:
        return True
    return doc_type in expected
