# STATUS: oneshot (2026-07-05)
"""Backfill : normalise les DOI du stock et purge les négatifs de lookup périmés.

`clean_doi` est appliqué à toutes les écritures de DOI et avant chaque appel HTTP
par DOI ; il a aussi été durci (encodage pourcent, tirets Unicode, markup de fin,
listes au point-virgule, préfixe de schéma `doi:`, idempotence par point fixe). Le
stock déjà en base porte encore des formes non normalisées (legacy). Ce one-shot
les rattrape sans re-fetcher les sources. Idempotent (`clean_doi` l'est).

Deux opérations :

1. **Purge des négatifs de lookup périmés.** Un DOI « non trouvé » mémorisé sous
   une forme sale n'a jamais été interrogé sous sa forme propre : le négatif est
   invalide. On le supprime pour que la forme propre soit re-tentée au prochain
   run (les candidats cross-import sont maintenant nettoyés en amont).
   - `staging` : stubs not-found DOI-natifs (crossref/datacite) à `doi` sale ;
   - `doi_lookups` : misses cross-import (hal/openalex/wos/scanr) à `doi` sale.
   Les négatifs déjà propres sont conservés (vrai miss).

2. **Normalisation en place des colonnes source de vérité :**
   - `staging.doi` (records réels) ;
   - `source_publications.doi` — avec `keys_dirty = true` : un DOI est une clé de
     confirmation, sa correction doit re-déclencher la réconciliation de
     composante (c'est elle qui fusionnera les publications devenues doublons une
     fois leurs DOI identiques) ;
   - `source_publications.external_ids.related_dois` (nettoyage + dédoublonnage) ;
   - `source_publications.meta.related_identifiers` (DOI des relations DataCite lues
     par la sous-étape cluster de `metadata_correction` pour faire converger versions,
     variantes et pièces de datasets sur l'œuvre canonique).

Les colonnes **dérivées** ne sont pas écrites ici : `publications.doi` (contrainte
UNIQUE, recomposé par `refresh_from_sources`) et `publication_relations.target_doi`
(table reconstruite par la phase `relations`). Elles se propagent au prochain run
des phases `publications` (réconciliation), `relations` et le refresh — leur volume
encore sale est seulement journalisé.

Après ce backfill, relancer les phases `metadata_correction` / `publications` /
`relations` (ou un run complet) pour propager aux dérivées et matérialiser les
fusions (dont les pièces de datasets absorbées par leur parent).

Usage :
    python -m interfaces.cli.oneshot.backfill_clean_dois            # dry-run (rapport)
    python -m interfaces.cli.oneshot.backfill_clean_dois --apply    # exécution
"""

from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import Connection, text

from domain.publications.identifiers import clean_doi
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("backfill_clean_dois", os.path.dirname(__file__))


def _purge_dirty_negatives(conn: Connection, apply: bool) -> None:
    """Supprime les négatifs de lookup (stubs `staging` not-found + `doi_lookups`)
    dont le `doi` n'est pas déjà sous forme canonique."""
    stubs = conn.execute(
        text(
            "SELECT source::text AS source, source_id, doi FROM staging "
            "WHERE not_found_at IS NOT NULL AND doi IS NOT NULL"
        )
    ).all()
    stub_del = [{"s": r.source, "sid": r.source_id} for r in stubs if clean_doi(r.doi) != r.doi]
    log.info("staging stubs not-found à doi sale : %d / %d", len(stub_del), len(stubs))
    if apply and stub_del:
        conn.execute(
            text("DELETE FROM staging WHERE source = CAST(:s AS source_type) AND source_id = :sid"),
            stub_del,
        )

    lookups = conn.execute(text("SELECT source::text AS source, doi FROM doi_lookups")).all()
    lk_del = [{"s": r.source, "d": r.doi} for r in lookups if clean_doi(r.doi) != r.doi]
    log.info("doi_lookups à doi sale : %d / %d", len(lk_del), len(lookups))
    if apply and lk_del:
        conn.execute(
            text("DELETE FROM doi_lookups WHERE source = CAST(:s AS source_type) AND doi = :d"),
            lk_del,
        )


def _clean_staging_doi(conn: Connection, apply: bool) -> None:
    """Normalise `staging.doi` des records réels (hors stubs not-found)."""
    rows = conn.execute(
        text(
            "SELECT source::text AS source, source_id, doi FROM staging "
            "WHERE doi IS NOT NULL AND not_found_at IS NULL"
        )
    ).all()
    upd = [
        {"s": r.source, "sid": r.source_id, "c": c}
        for r in rows
        if (c := clean_doi(r.doi)) != r.doi
    ]
    log.info("staging.doi à normaliser : %d / %d", len(upd), len(rows))
    if apply and upd:
        conn.execute(
            text(
                "UPDATE staging SET doi = :c "
                "WHERE source = CAST(:s AS source_type) AND source_id = :sid"
            ),
            upd,
        )


def _clean_source_publication_doi(conn: Connection, apply: bool) -> None:
    """Normalise `source_publications.doi` et pose `keys_dirty` (re-réconciliation)."""
    rows = conn.execute(text("SELECT id, doi FROM source_publications WHERE doi IS NOT NULL")).all()
    upd = [{"id": r.id, "c": c} for r in rows if (c := clean_doi(r.doi)) != r.doi]
    log.info(
        "source_publications.doi à normaliser : %d / %d (keys_dirty posé)", len(upd), len(rows)
    )
    if apply and upd:
        conn.execute(
            text("UPDATE source_publications SET doi = :c, keys_dirty = true WHERE id = :id"),
            upd,
        )


def _clean_related_dois(conn: Connection, apply: bool) -> None:
    """Normalise et dédoublonne `source_publications.external_ids.related_dois`."""
    rows = conn.execute(
        text(
            "SELECT id, external_ids FROM source_publications "
            "WHERE jsonb_typeof(external_ids -> 'related_dois') = 'array'"
        )
    ).all()
    upd: list[dict] = []
    for r in rows:
        ext = dict(r.external_ids)
        rel = ext.get("related_dois") or []
        cleaned = list(dict.fromkeys(c for x in rel if (c := clean_doi(x))))
        if cleaned == rel:
            continue
        if cleaned:
            ext["related_dois"] = cleaned
        else:
            ext.pop("related_dois", None)
        upd.append({"id": r.id, "ext": json.dumps(ext)})
    log.info("source_publications.related_dois à normaliser : %d / %d", len(upd), len(rows))
    if apply and upd:
        conn.execute(
            text(
                "UPDATE source_publications SET external_ids = CAST(:ext AS jsonb) WHERE id = :id"
            ),
            upd,
        )


def _clean_related_identifiers_meta(conn: Connection, apply: bool) -> None:
    """Normalise le `doi` de chaque entrée `meta.related_identifiers` (relations DataCite).

    C'est la forme lue par la sous-étape cluster de `metadata_correction` pour faire converger
    versions, variantes et pièces de datasets. Une entrée dont le `doi` devient inutilisable
    (`clean_doi` → None) est retirée. Pas de `keys_dirty` : `metadata_correction` re-scanne
    `meta.related_identifiers` à chaque run, donc la convergence — et le `keys_dirty` qu'elle
    pose sur les pièces — suit au prochain passage."""
    rows = conn.execute(
        text(
            "SELECT id, meta FROM source_publications "
            "WHERE jsonb_typeof(meta -> 'related_identifiers') = 'array'"
        )
    ).all()
    upd: list[dict] = []
    for r in rows:
        new_rels: list = []
        changed = False
        for el in r.meta["related_identifiers"]:
            doi = el.get("doi") if isinstance(el, dict) else None
            cleaned = clean_doi(doi) if doi is not None else None
            if isinstance(el, dict) and cleaned != doi:
                changed = True
                if cleaned is None:
                    continue  # relation sans DOI exploitable → retirée
                new_rels.append({**el, "doi": cleaned})
            else:
                new_rels.append(el)
        if not changed:
            continue
        meta = dict(r.meta)
        if new_rels:
            meta["related_identifiers"] = new_rels
        else:
            meta.pop("related_identifiers", None)
        upd.append({"id": r.id, "meta": json.dumps(meta)})
    log.info(
        "source_publications.meta.related_identifiers à normaliser : %d / %d", len(upd), len(rows)
    )
    if apply and upd:
        conn.execute(
            text("UPDATE source_publications SET meta = CAST(:meta AS jsonb) WHERE id = :id"),
            upd,
        )


def _report_derived(conn: Connection) -> None:
    """Journalise le volume des colonnes dérivées encore sales (non écrites ici)."""
    pubs = conn.execute(text("SELECT doi FROM publications WHERE doi IS NOT NULL")).all()
    n_pub = sum(1 for r in pubs if clean_doi(r.doi) != r.doi)
    rels = conn.execute(
        text("SELECT target_doi FROM publication_relations WHERE target_doi IS NOT NULL")
    ).all()
    n_rel = sum(1 for r in rels if clean_doi(r.target_doi) != r.target_doi)
    log.info(
        "Dérivé (recomposé au prochain run des phases, non écrit ici) : "
        "publications.doi sales=%d, publication_relations.target_doi sales=%d",
        n_pub,
        n_rel,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Applique les écritures (défaut : dry-run / rapport)."
    )
    args = parser.parse_args()

    if not args.apply:
        log.info("DRY-RUN (rapport seul) — relancer avec --apply pour écrire")

    engine = get_sync_engine()
    with engine.connect() as conn:
        _purge_dirty_negatives(conn, args.apply)
        _clean_staging_doi(conn, args.apply)
        _clean_source_publication_doi(conn, args.apply)
        _clean_related_dois(conn, args.apply)
        _clean_related_identifiers_meta(conn, args.apply)
        _report_derived(conn)
        if args.apply:
            conn.commit()
            log.info("✓ backfill appliqué")
        else:
            log.info("DRY-RUN terminé — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
