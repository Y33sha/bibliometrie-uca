"""Sujets donnés par un enregistrement source. L'écriture est commune aux normaliseurs.

Les sujets d'un enregistrement source se réécrivent à chaque normalisation, comme ses localisations : le dernier import fait autorité. Chaque sujet entre dans `subjects` avec ses ancêtres, identifié par son vocabulaire et son code. Son libellé, son niveau et son parent suivent le dernier enregistrement source normalisé.
"""

import json
from collections.abc import Mapping, Sequence

from sqlalchemy import Connection, text

from domain.normalize import normalize_text, to_plain_text
from domain.subjects.subject import Subject, SubjectLink

# Une instruction par niveau, de la racine aux feuilles : le parent d'un sujet est écrit par l'instruction du niveau précédent.
_UPSERT_LEVEL = text("""
    WITH incoming AS (
        SELECT CAST(t.vocabulary AS subject_vocabulary) AS vocabulary, t.code, t.label,
               t.label_normalized, t.level, p.id AS parent_id
        FROM jsonb_to_recordset(CAST(:subjects AS jsonb)) AS t(
            vocabulary text, code text, label text, label_normalized text, level smallint,
            parent_code text
        )
        LEFT JOIN subjects p
            ON p.vocabulary = CAST(t.vocabulary AS subject_vocabulary) AND p.code = t.parent_code
    )
    INSERT INTO subjects (vocabulary, code, label, label_normalized, level, parent_id)
    SELECT vocabulary, code, label, label_normalized, level, parent_id FROM incoming
    ON CONFLICT (vocabulary, code) DO UPDATE SET
        label = EXCLUDED.label,
        label_normalized = EXCLUDED.label_normalized,
        level = EXCLUDED.level,
        parent_id = EXCLUDED.parent_id
    WHERE (subjects.label, subjects.level, subjects.parent_id)
        IS DISTINCT FROM (EXCLUDED.label, EXCLUDED.level, EXCLUDED.parent_id)
""")

_REPLACE_LINKS = text("""
    WITH incoming AS (
        SELECT t.source_record_id, s.id AS subject_id, t.score
        FROM jsonb_to_recordset(CAST(:links AS jsonb)) AS t(
            source_record_id integer, vocabulary text, code text, score real
        )
        JOIN subjects s
            ON s.vocabulary = CAST(t.vocabulary AS subject_vocabulary) AND s.code = t.code
    ),
    removed AS (
        DELETE FROM source_record_subjects srs
        WHERE srs.source_record_id = ANY(:ids)
          AND NOT EXISTS (
              SELECT 1 FROM incoming i
              WHERE i.source_record_id = srs.source_record_id AND i.subject_id = srs.subject_id
          )
    )
    INSERT INTO source_record_subjects (source_record_id, subject_id, score)
    SELECT source_record_id, subject_id, score FROM incoming
    ON CONFLICT (source_record_id, subject_id) DO UPDATE SET score = EXCLUDED.score
    WHERE source_record_subjects.score IS DISTINCT FROM EXCLUDED.score
""")


def _key(subject: Subject) -> tuple[str, str]:
    return subject.vocabulary.value, subject.code


def _subject_row(subject: Subject) -> dict[str, object]:
    label = to_plain_text(subject.label)
    return {
        "vocabulary": subject.vocabulary.value,
        "code": subject.code,
        "label": label,
        "label_normalized": normalize_text(label),
        "level": subject.level,
        "parent_code": subject.parent.code if subject.parent else None,
    }


def _merged_scores(links: Sequence[SubjectLink]) -> dict[tuple[str, str], float | None]:
    """Renvoie le score de chaque sujet distinct de `links` : le plus haut, quand la source donne un sujet deux fois."""
    scores: dict[tuple[str, str], float | None] = {}
    for link in links:
        key = _key(link.subject)
        known = scores.get(key)
        scores[key] = link.score if known is None else max(known, link.score or known)
    return scores


class SourceRecordSubjectStore:
    """Écriture des sujets des enregistrements sources, sur la connexion `conn`."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def replace_subjects(self, source_record_id: int, links: Sequence[SubjectLink]) -> None:
        """Réécrit les sujets de l'enregistrement source avec `links`. Chaque sujet est écrit dans `subjects` avec ses ancêtres."""
        self.replace_subjects_bulk({source_record_id: links})

    def replace_subjects_bulk(
        self, links_by_source_record: Mapping[int, Sequence[SubjectLink]]
    ) -> None:
        """Réécrit les sujets de plusieurs enregistrements sources, en une instruction par niveau puis une instruction pour les liens."""
        levels: dict[int, dict[tuple[str, str], dict[str, object]]] = {}
        for links in links_by_source_record.values():
            for link in links:
                for subject in link.subject.lineage():
                    levels.setdefault(subject.level, {})[_key(subject)] = _subject_row(subject)
        for level in sorted(levels):
            self._conn.execute(
                _UPSERT_LEVEL, {"subjects": json.dumps(list(levels[level].values()))}
            )
        rows = [
            {
                "source_record_id": source_record_id,
                "vocabulary": vocabulary,
                "code": code,
                "score": score,
            }
            for source_record_id, links in links_by_source_record.items()
            for (vocabulary, code), score in _merged_scores(links).items()
        ]
        self._conn.execute(
            _REPLACE_LINKS, {"ids": list(links_by_source_record), "links": json.dumps(rows)}
        )
