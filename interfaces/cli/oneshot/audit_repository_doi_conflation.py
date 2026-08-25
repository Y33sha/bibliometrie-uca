# STATUS: oneshot (2026-08-25)
"""Audit (lecture seule) : DOI d'entrepôt DataCite sur une publication de revue (conflation article/dépôt).

Liste les publications portant un `journal_id` dont le DOI canonique est enregistré via DataCite par un entrepôt multi-éditeurs (arXiv, Zenodo, OSF, dépôts institutionnels). Ce profil signale une conflation probable entre un article de revue et un dépôt (preprint, jeu de données) réunis sur une même publication.

Le triage repose sur la diversité d'éditeurs : un client DataCite d'entrepôt côtoie beaucoup d'éditeurs de journaux distincts, un client d'éditeur-plateforme (Classiques Garnier, une bibliothèque universitaire) un seul, lui-même. Le seuil `MIN_PUBLISHER_DIVERSITY` sélectionne les clients à examiner.

N'écrit rien.

Usage :
    python -m interfaces.cli.oneshot.audit_repository_doi_conflation
"""

from sqlalchemy import text

from infrastructure.db.engine import get_sync_engine

# Un client DataCite côtoyant au moins ce nombre d'éditeurs de journaux distincts est traité
# comme candidat « entrepôt multi-éditeurs ». Seuil de triage, à ajuster à la lecture.
MIN_PUBLISHER_DIVERSITY = 3

# Publications de revue (journal_id présent) dont le DOI canonique est un DOI DataCite.
_BASE = """
    FROM publications p
    JOIN journals j ON j.id = p.journal_id
    JOIN publishers pub ON pub.id = j.publisher_id
    JOIN doi_prefixes dp ON dp.prefix = split_part(p.doi, '/', 1)
    WHERE p.doi IS NOT NULL AND dp.ra = 'DataCite'
"""


def main() -> int:
    engine = get_sync_engine()
    with engine.connect() as conn:
        total = conn.execute(text("SELECT count(*) " + _BASE)).scalar()
        print(f"Publications de revue (journal_id) portant un DOI DataCite : {total}\n")

        print(
            "Par client DataCite — diversité d'éditeurs de journaux côtoyés (entrepôts en tête) :"
        )
        print(f"  {'client':26s} {'pubs':>5s} {'éditeurs':>9s}  nom du client")
        clients = conn.execute(
            text(
                "SELECT dp.datacite_client_symbol AS sym, dp.client_name_normalized AS name, "
                "count(*) AS n_pubs, count(DISTINCT pub.name_normalized) AS n_pub "
                + _BASE
                + " GROUP BY 1, 2 ORDER BY n_pub DESC, n_pubs DESC"
            )
        ).all()
        for r in clients:
            flag = "◄ candidat entrepôt" if r.n_pub >= MIN_PUBLISHER_DIVERSITY else ""
            print(
                f"  {(r.sym or '?'):26s} {r.n_pubs:5d} {r.n_pub:9d}  {(r.name or '')[:30]:30s} {flag}"
            )

        print(
            f"\nPublications à examiner (clients à ≥ {MIN_PUBLISHER_DIVERSITY} éditeurs distincts) :"
        )
        rows = conn.execute(
            text(
                "SELECT p.id, p.doc_type, j.title AS journal, pub.name AS journal_publisher, "
                "dp.client_name_normalized AS dc_client "
                + _BASE
                + " AND dp.datacite_client_symbol IN ("
                "   SELECT dp2.datacite_client_symbol "
                "   FROM publications p2 "
                "   JOIN journals j2 ON j2.id = p2.journal_id "
                "   JOIN publishers pub2 ON pub2.id = j2.publisher_id "
                "   JOIN doi_prefixes dp2 ON dp2.prefix = split_part(p2.doi, '/', 1) "
                "   WHERE p2.doi IS NOT NULL AND dp2.ra = 'DataCite' "
                "   GROUP BY dp2.datacite_client_symbol "
                "   HAVING count(DISTINCT pub2.name_normalized) >= :seuil"
                " ) ORDER BY dc_client, p.id"
            ),
            {"seuil": MIN_PUBLISHER_DIVERSITY},
        ).all()
        print(f"  ({len(rows)} publications)\n")
        for r in rows:
            journal = (r.journal or "")[:34]
            publisher = (r.journal_publisher or "")[:24]
            print(
                f"  #{r.id:<7d} [{r.doc_type:12s}] « {journal:34s} » / {publisher:24s}  ⟂  {r.dc_client}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
