# STATUS: oneshot (2026-08-28)
"""Réaligne les clés de rapprochement sur les valeurs mises à plat, et fusionne les doublons que cela révèle.

La mise à plat des valeurs affichées (`backfill_strip_markup`) n'a pas touché aux colonnes normalisées, qui restaient calculées sur la valeur reçue : une revue affichée `Wood & Fire Safety` gardait la clé `wood amp fire safety`. Les points d'écriture dérivent maintenant les deux de la même valeur ; ce script rattrape le stock.

Trois temps :

1. **Clés recalculées** — `journals.title_normalized`, `publishers.name_normalized`, `source_publications.title_normalized`. Les formes de nom sont laissées en l'état : ce ne sont pas des valeurs dérivées du parent mais les variantes sous lesquelles il a été rencontré, accumulées pour les rapprochements suivants. Une variante issue d'un titre encodé n'apparie plus rien une fois les écritures assainies, mais elle ne nuit pas — et la fusion consolide celles des entités absorbées.

2. **Doublons fusionnés** — deux revues (ou deux éditeurs) que le recalcul réunit sous la même clé désignent la même entité, séparée par le seul encodage de son nom. La fusion passe par le service métier, qui transfère les publications, requalifie ce qui doit l'être et journalise l'événement. Survit la ligne qui porte le plus de publications, puis celle dont les métadonnées sont les plus complètes ; les autres y sont absorbées.

3. **Signalé sans être traité** — les identités d'auteur dont le nom normalisé reste périmé. Les repointer demande de recalculer leur empreinte et de purger les orphelines (cf. `backfill_strip_author_name_ids`) ; le script les nomme pour qu'on décide.

Usage :
    python -m interfaces.cli.oneshot.backfill_renormalize_after_strip_markup            # exécution
    python -m interfaces.cli.oneshot.backfill_renormalize_after_strip_markup --dry-run  # rapport seul
"""

from __future__ import annotations

import argparse
import os
from collections import defaultdict

from sqlalchemy import Connection, text

from application.services.journals.core import merge_journals
from application.services.publishers.core import merge_publishers
from domain.normalize import normalize_name_form, normalize_text
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.pipeline.metadata_correction import PgMetadataCorrectionQueries
from infrastructure.repositories.journal_repository import PgJournalRepository
from infrastructure.repositories.publication_repository import PgPublicationRepository
from infrastructure.repositories.publisher_repository import PgPublisherRepository

log = setup_logger("backfill_renormalize_after_strip_markup", os.path.dirname(__file__))

# (table, colonne source, colonne normalisée)
_CLES = [
    ("journals", "title", "title_normalized"),
    ("publishers", "name", "name_normalized"),
    ("source_publications", "title", "title_normalized"),
]


def _recalculer_cles(conn: Connection, apply: bool) -> None:
    """Recalcule les colonnes normalisées dont la valeur ne correspond plus à leur source."""
    for table, source, norm in _CLES:
        rows = conn.execute(
            text(f"SELECT id, {source} AS v, {norm} AS n FROM {table} WHERE {source} IS NOT NULL")
        ).all()
        perimees = [(r.id, normalize_text(r.v)) for r in rows if normalize_text(r.v) != (r.n or "")]
        log.info("%s.%s : %d clés à recalculer", table, norm, len(perimees))
        if apply and perimees:
            conn.execute(
                text(f"UPDATE {table} SET {norm} = :n WHERE id = :id"),
                [{"id": i, "n": n} for i, n in perimees],
            )


def _groupes_convergents(conn: Connection, table: str, source: str) -> list[list[int]]:
    """Identifiants que le recalcul réunit sous une même clé, du plus riche au plus pauvre.

    Un groupe n'est retenu que si le recalcul **crée** le rapprochement : ses membres portaient
    des clés distinctes et n'en portent plus qu'une. Grouper sur la seule clé recalculée
    ramasserait aussi tous les doublons préexistants — deux revues homonymes sous des éditeurs
    différents en sont, et les fusionner ne relève pas de ce script.

    Richesse = nombre de publications rattachées, puis nombre d'identifiants renseignés : la
    ligne complète survit, la ligne partielle y est absorbée.
    """
    if table == "journals":
        sql = """
            SELECT j.id, j.title AS v, j.title_normalized AS stockee,
                   (SELECT count(*) FROM publications p WHERE p.journal_id = j.id) AS n,
                   (CASE WHEN j.issn IS NOT NULL THEN 1 ELSE 0 END
                    + CASE WHEN j.eissn IS NOT NULL THEN 1 ELSE 0 END
                    + CASE WHEN j.issnl IS NOT NULL THEN 1 ELSE 0 END) AS ids
            FROM journals j
        """
    else:
        sql = """
            SELECT p.id, p.name AS v, p.name_normalized AS stockee,
                   (SELECT count(*) FROM journals j WHERE j.publisher_id = p.id) AS n,
                   (CASE WHEN p.openalex_id IS NOT NULL THEN 1 ELSE 0 END) AS ids
            FROM publishers p
        """
    par_cle: dict[str, list[tuple[int, int, int, str]]] = defaultdict(list)
    for r in conn.execute(text(sql)):
        par_cle[normalize_text(r.v)].append((r.n, r.ids, r.id, r.stockee or ""))
    groupes = []
    for cle, membres in par_cle.items():
        if not cle or len(membres) < 2:
            continue
        if len({stockee for *_, stockee in membres}) < 2:
            continue  # déjà réunis avant le recalcul : doublon préexistant, hors périmètre
        groupes.append([i for _, _, i, _ in sorted(membres, reverse=True)])
    return groupes


def _fusionner(
    conn: Connection,
    groupes_revues: list[list[int]],
    groupes_editeurs: list[list[int]],
    apply: bool,
) -> None:
    """Fusionne les revues puis les éditeurs que le recalcul réunit sous une même clé.

    Les groupes sont relevés avant le recalcul : une fois les clés réécrites, plus rien ne
    distingue un rapprochement que ce script vient de créer d'un doublon préexistant.
    """
    corrections = PgMetadataCorrectionQueries()
    journal_repo = PgJournalRepository(conn)
    publisher_repo = PgPublisherRepository(conn)
    publication_repo = PgPublicationRepository(conn)

    groupes = groupes_revues
    log.info("revues : %d groupes à fusionner", len(groupes))
    for ids in groupes:
        cible, sources = ids[0], ids[1:]
        log.info("    revue %d absorbe %s", cible, sources)
        if apply:
            for source_id in sources:
                merge_journals(
                    cible,
                    source_id,
                    conn=conn,
                    correction_queries=corrections,
                    repo=journal_repo,
                    publication_repo=publication_repo,
                )

    groupes = groupes_editeurs
    log.info("éditeurs : %d groupes à fusionner", len(groupes))
    for ids in groupes:
        cible, sources = ids[0], ids[1:]
        log.info("    éditeur %d absorbe %s", cible, sources)
        if apply:
            for source_id in sources:
                merge_publishers(
                    cible,
                    source_id,
                    conn=conn,
                    correction_queries=corrections,
                    publisher_repo=publisher_repo,
                    journal_repo=journal_repo,
                    publication_repo=publication_repo,
                )


def _signaler_identites_perimees(conn: Connection) -> None:
    """Nomme les identités d'auteur dont le nom normalisé ne correspond plus à la signature."""
    rows = conn.execute(
        text(
            "SELECT DISTINCT aik.id, sa.raw_author_name AS raw, "
            "aik.author_name_normalized AS norm "
            "FROM source_authorships sa JOIN author_identifying_keys aik ON aik.id = sa.identity_id "
            "WHERE sa.raw_author_name ~ '&|<'"
        )
    ).all()
    perimees = [r for r in rows if normalize_name_form(r.raw) != (r.norm or "")]
    log.info("identités d'auteur périmées : %d (non traitées)", len(perimees))
    for r in perimees:
        log.info("    %d %r → attendu %r", r.id, r.raw[:50], normalize_name_form(r.raw)[:50])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Rapport seul : n'écrit rien (défaut : applique)."
    )
    args = parser.parse_args()
    apply = not args.dry_run
    if not apply:
        log.info("DRY-RUN (rapport seul) — retirer --dry-run pour écrire")

    engine = get_sync_engine()
    with engine.connect() as conn:
        # Relevé avant toute écriture : la détection compare la clé recalculée à la clé stockée,
        # et le recalcul efface justement cette différence.
        groupes_revues = _groupes_convergents(conn, "journals", "title")
        groupes_editeurs = _groupes_convergents(conn, "publishers", "name")

        _recalculer_cles(conn, apply)
        if apply:
            conn.commit()
        _fusionner(conn, groupes_revues, groupes_editeurs, apply)
        _signaler_identites_perimees(conn)
        if apply:
            conn.commit()
            log.info("✓ backfill appliqué")
        else:
            log.info("DRY-RUN terminé — aucune écriture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
