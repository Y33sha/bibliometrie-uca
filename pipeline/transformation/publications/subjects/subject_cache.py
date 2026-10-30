"""Outils partagés par les lecteurs de sujets des sources : dédoublonnage des libellés, cache des identifiants de sujets."""

from pipeline.transformation.publications.subjects.subject_store import (
    PublicationSubjectLink,
    SubjectStore,
)


def dedup_strs(values: object) -> list[str]:
    """Filtre les valeurs autres que des chaînes et les chaînes vides, puis dédoublonne sur `lower(s)`. Garde l'ordre et la casse de la première occurrence."""
    if not isinstance(values, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        s = v.strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


class SubjectCache:
    """Cache mémoire des `subject_id` déjà écrits sur la connexion courante, par `lower(label)`. Il évite les UPSERT redondants d'un libellé fréquent."""

    def __init__(self, store: SubjectStore) -> None:
        self._store = store
        self._cache: dict[str, int] = {}

    def get_or_upsert(self, *, label: str, language: str | None = None) -> int:
        """Renvoie l'id du sujet de ce libellé, écrit par UPSERT au premier passage."""
        key = label.strip().lower()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        sid = self._store.upsert_subject(label=label, language=language)
        self._cache[key] = sid
        return sid

    def link_bulk(self, *, source: str, rows: list[PublicationSubjectLink]) -> int:
        return self._store.link_publication_subjects_bulk(source=source, rows=rows)

    def stats(self) -> dict[str, int]:
        return {"subjects": len(self._cache)}
