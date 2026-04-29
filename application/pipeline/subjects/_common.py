"""Helpers partagés entre les ingestors par source."""

from typing import Any

from application.ports.subjects import SubjectsQueries


def dedup_strs(values: Any) -> list[str]:
    """Filtre les non-str et chaînes vides, déduplique sur `lower(s)` en
    préservant l'ordre et la casse du premier insert.

    Utilisé par tous les ingestors avant de pousser les keywords/topics
    vers `upsert_*_subject` : évite des allers-retours SQL inutiles
    (l'index unique partiel ferait le boulot, mais autant ne pas le solliciter).
    """
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
    """Cache mémoire des `subject_id` déjà upsertés sur la connexion courante.

    Sur 40k publications, un même mot-clé/concept revient des centaines de fois.
    Sans cache, chaque occurrence déclenche un round-trip SQL pour le UPSERT
    (qui est essentiellement un SELECT côté DB grâce au DO UPDATE SET label =
    subjects.label). Le cache élimine ces appels redondants.

    Clés :
    - libres   : (lower(label), language or '')
    - concepts : (ontology, ontology_id)

    Le cache n'est valide qu'au sein d'une transaction : si un autre process
    insère un subject entre-temps, le UPSERT serait quand même correct (on
    rate juste le hit cache pour cette clé). Il n'y a pas de risque
    d'incohérence puisque chaque clé pointe vers un id stable.

    Le cache porte aussi le port `SubjectsQueries` pour que les ingestors
    n'aient à connaître qu'un seul objet (couche application pure).
    """

    def __init__(self, queries: SubjectsQueries) -> None:
        self._queries = queries
        self._free: dict[tuple[str, str], int] = {}
        self._concept: dict[tuple[str, str], int] = {}

    def get_or_upsert_free(
        self,
        cur: Any,
        *,
        label: str,
        language: str | None = None,
    ) -> int:
        key = (label.strip().lower(), language or "")
        cached = self._free.get(key)
        if cached is not None:
            return cached
        sid = self._queries.upsert_free_subject(cur, label=label, language=language)
        self._free[key] = sid
        return sid

    def get_or_upsert_concept(
        self,
        cur: Any,
        *,
        ontology: str,
        ontology_id: str,
        label: str,
        language: str | None = None,
        parent_id: int | None = None,
        level: int | None = None,
    ) -> int:
        key = (ontology, ontology_id)
        cached = self._concept.get(key)
        if cached is not None:
            return cached
        sid = self._queries.upsert_concept_subject(
            cur,
            ontology=ontology,
            ontology_id=ontology_id,
            label=label,
            language=language,
            parent_id=parent_id,
            level=level,
        )
        self._concept[key] = sid
        return sid

    def link_bulk(
        self,
        cur: Any,
        *,
        source: str,
        rows: list[tuple[int, int, float | None]],
    ) -> int:
        return self._queries.link_publication_subjects_bulk(cur, source=source, rows=rows)

    def stats(self) -> dict[str, int]:
        return {"free": len(self._free), "concept": len(self._concept)}
