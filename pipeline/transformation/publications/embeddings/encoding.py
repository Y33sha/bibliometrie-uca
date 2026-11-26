"""Tâche `encode_publications` : embedding de chaque publication (`publication_embeddings`).

Le texte encodé est le titre de la publication, suivi du plus long résumé de ses enregistrements sources. Une publication est à encoder sans vecteur, ou quand le modèle ou l'empreinte du début de son texte diffère. Le plafond `embeddings_max_per_run` borne le nombre de publications encodées par run ; les plus petits identifiants passent en premier. La commande `interfaces/cli/maintenance/encode_publications.py` encode le stock hors run.
"""

import logging

from sqlalchemy import Connection, text

from domain.config import ConfigKey
from infrastructure.embeddings import FastembedEncoder, TextEncoder
from pipeline.graph import Task
from pipeline.runtime.config import cap
from pipeline.runtime.context import OpenTransaction, PhaseContext
from pipeline.runtime.observability.log_format import BRANCH
from pipeline.runtime.observability.metrics import PhaseMetrics
from pipeline.runtime.observability.progress import track_progress

HASHED_CHARACTERS = 1_000
"""Caractères du texte couverts par l'empreinte. Le modèle lit environ 500 caractères : une modification au-delà laisse le vecteur inchangé."""
ENCODED_CHARACTERS = 2_000
"""Caractères du texte transmis au modèle, qui tronque lui-même à sa longueur de lecture."""
BATCH = 256
"""Publications encodées puis écrites par transaction."""

_TEXTS_SQL = """
    SELECT p.id, p.title || coalesce('. ' || a.abstract, '') AS text
    FROM publications p
    LEFT JOIN LATERAL (
        SELECT sr.abstract FROM source_records sr
        WHERE sr.publication_id = p.id AND sr.abstract <> ''
        ORDER BY length(sr.abstract) DESC, sr.id
        LIMIT 1
    ) a ON true
"""
"""Texte encodé de chaque publication : titre, puis plus long résumé de ses enregistrements sources."""

_PENDING_SQL = text(f"""
    WITH texts AS ({_TEXTS_SQL})
    SELECT t.id, md5(left(t.text, {HASHED_CHARACTERS})) AS text_hash
    FROM texts t
    LEFT JOIN publication_embeddings e ON e.publication_id = t.id
    WHERE e.publication_id IS NULL OR e.model <> :model OR e.text_hash <> md5(left(t.text, {HASHED_CHARACTERS}))
    ORDER BY t.id
""")

_TEXTS_OF_SQL = text(f"""
    WITH texts AS ({_TEXTS_SQL} WHERE p.id = ANY(:ids))
    SELECT id, left(text, {ENCODED_CHARACTERS}) AS text FROM texts
""")

_UPSERT_SQL = text("""
    INSERT INTO publication_embeddings (publication_id, model, text_hash, vector, computed_at)
    VALUES (:publication_id, :model, :text_hash, CAST(:vector AS real[]), now())
    ON CONFLICT (publication_id) DO UPDATE
    SET model = EXCLUDED.model, text_hash = EXCLUDED.text_hash, vector = EXCLUDED.vector, computed_at = now()
""")


def pending_publications(conn: Connection, model: str) -> list[tuple[int, str]]:
    """Renvoie les publications à encoder, avec l'empreinte de leur texte, par identifiant croissant."""
    return [(r.id, r.text_hash) for r in conn.execute(_PENDING_SQL, {"model": model})]


def encode_publications(
    open_tx: OpenTransaction, encoder: TextEncoder, limit: int | None, logger: logging.Logger
) -> PhaseMetrics:
    """Encode les publications à encoder, au plus `limit` (`None` : toutes), par lots écrits chacun dans sa transaction."""
    with open_tx() as conn:
        pending = pending_publications(conn, encoder.model)
    selected = pending if limit is None else pending[:limit]
    with track_progress(
        len(selected), f"{BRANCH}publications encodées", logger, erase=True
    ) as progress:
        for start in range(0, len(selected), BATCH):
            batch = dict(selected[start : start + BATCH])
            with open_tx() as conn:
                texts = dict(conn.execute(_TEXTS_OF_SQL, {"ids": list(batch)}).all())
                ids = [i for i in batch if i in texts]
                vectors = encoder.encode([texts[i] for i in ids])
                if ids:
                    conn.execute(
                        _UPSERT_SQL,
                        [
                            {
                                "publication_id": i,
                                "model": encoder.model,
                                "text_hash": batch[i],
                                "vector": v,
                            }
                            for i, v in zip(ids, vectors, strict=True)
                        ],
                    )
            progress.advance(len(batch))
    remaining = len(pending) - len(selected)
    return PhaseMetrics(
        new=len(selected),
        extras={"embeddings_pending": remaining},
        report=f"{len(selected)} publications encodées, {remaining} encore à encoder",
    )


def _run(ctx: PhaseContext) -> PhaseMetrics:
    with ctx.open_tx() as conn:
        limit = cap(conn, ConfigKey.EMBEDDINGS_MAX_PER_RUN)
    return encode_publications(ctx.open_tx, FastembedEncoder(), limit, ctx.logger)


TASKS = (
    Task(
        "encode_publications",
        reads=(
            "config",
            "publications.id",
            "publications.title",
            "source_records.publication_id",
            "source_records.abstract",
            "publication_embeddings",
        ),
        writes=("publication_embeddings",),
        previous_runs=(
            # Publications supprimées et enregistrements sources détachés par `finalize.purge_publications`.
            "publications.id",
            "publications.title",
            "source_records.publication_id",
        ),
        run=_run,
        label="Embeddings des publications",
    ),
)
