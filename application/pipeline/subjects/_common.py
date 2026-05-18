"""Helpers partagés entre les ingestors par source."""

from typing import Any

from sqlalchemy import Connection

from application.ports.pipeline.subjects import OntologyEntry, SubjectsQueries


def dedup_strs(values: object) -> list[str]:
    """Filtre les non-str et chaînes vides, déduplique sur `lower(s)` en
    préservant l'ordre et la casse du premier insert."""
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


# Forme cache d'une entrée d'ontologie : on track les codes déjà poussés
# et le couple (level, parent) déjà connu pour cette ontologie. Si une
# nouvelle demande couvre uniquement des codes connus AVEC le même couple
# (level, parent), on évite l'UPSERT SQL.
_PushedOntology = dict[str, Any]  # {"codes": set[str], "level": ..., "parent": ...}


class SubjectCache:
    """Cache mémoire des `subject_id` déjà upsertés sur la connexion courante.

    Clé = `lower(label)`. Sur 40k publications, un même libellé revient des
    centaines de fois ; le cache élimine les UPSERTs SQL redondants — la
    fusion JSONB en `ON CONFLICT` est coûteuse, autant l'éviter quand on a
    déjà poussé l'ontologie demandée.

    Pour gérer la fusion correctement, on mémorise pour chaque label
    `(subject_id, ontologies déjà poussées)` au format :
        {ontology_name: {"codes": set[str], "level": ..., "parent": ...}}
    Si une demande couvre uniquement des paires (codes/level/parent) déjà
    connues, on court-circuite.
    """

    def __init__(self, queries: SubjectsQueries) -> None:
        self._queries = queries
        # key → (subject_id, dict d'ontologies poussées)
        self._cache: dict[str, tuple[int, dict[str, _PushedOntology]]] = {}

    def get_or_upsert(
        self,
        conn: Connection,
        *,
        label: str,
        language: str | None = None,
        ontologies: dict[str, OntologyEntry] | None = None,
    ) -> int:
        """Retourne l'id du sujet pour ce label (UPSERT au besoin).

        Court-circuite si :
        - le label est connu, ET
        - chaque ontologie demandée a tous ses `codes` déjà poussés ET
          son couple `(level, parent)` correspond à ce qu'on a déjà.
        """
        key = label.strip().lower()
        onto = ontologies or {}
        cached = self._cache.get(key)
        if cached is not None and self._covers(cached[1], onto):
            return cached[0]
        sid = self._queries.upsert_subject(
            conn,
            label=label,
            language=language,
            ontologies=ontologies,
        )
        if cached is not None:
            pushed = cached[1]
        else:
            pushed = {}
            self._cache[key] = (sid, pushed)
        for o, body in onto.items():
            slot = pushed.setdefault(o, {"codes": set(), "level": None, "parent": None})
            for c in body.get("codes", []) or []:
                slot["codes"].add(c)
            if slot["level"] is None and body.get("level") is not None:
                slot["level"] = body["level"]
            if slot["parent"] is None and body.get("parent") is not None:
                slot["parent"] = body["parent"]
        return sid

    @staticmethod
    def _covers(pushed: dict[str, _PushedOntology], requested: dict[str, OntologyEntry]) -> bool:
        """True si toutes les ontologies/codes/level/parent demandées sont
        déjà couvertes par `pushed`."""
        for o, body in requested.items():
            slot = pushed.get(o)
            if slot is None:
                return False
            for c in body.get("codes", []) or []:
                if c not in slot["codes"]:
                    return False
            req_level = body.get("level")
            if req_level is not None and slot["level"] != req_level:
                return False
            req_parent = body.get("parent")
            if req_parent is not None and slot["parent"] != req_parent:
                return False
        return True

    def link_bulk(
        self,
        conn: Connection,
        *,
        source: str,
        rows: list[tuple[int, int, float | None]],
    ) -> int:
        return self._queries.link_publication_subjects_bulk(conn, source=source, rows=rows)

    def stats(self) -> dict[str, int]:
        return {"subjects": len(self._cache)}
