# STATUS: maintenance
"""Importe les ORCID authentifiés par les chercheurs (fichier `data/authenticated_orcids.csv`).

Le fichier — sans en-tête, une ligne `email,orcid` par chercheur — liste les ORCID que leur
titulaire a lui-même authentifiés en se connectant à son compte ORCID. Chaque ligne est
rattachée à la personne via son email (`persons_rh.email`, comparaison insensible à la casse)
et reçoit le statut `authenticated`.

Cet import est **l'unique** contexte autorisé à écrire ce statut : un trigger Postgres
(`protect_authenticated_identifier`) rejette toute autre écriture de `authenticated` et interdit
d'en dégrader un existant. L'authentification faisant autorité sur l'identité, un ORCID déjà
rattaché à une autre personne est déplacé vers celle de l'email (chaque déplacement est signalé :
il révèle en général un doublon de personne à fusionner).

Idempotent : réappliqué sur un fichier inchangé, il ne produit aucune écriture.

Usage :
    python -m interfaces.cli.maintenance.import_authenticated_orcids [--file CHEMIN] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import os

from sqlalchemy import text

from application.persons.core import import_authenticated_orcids
from domain.persons.identifiers import normalize_orcid
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import person_repository

log = setup_logger("import_authenticated_orcids", os.path.dirname(__file__))

_DEFAULT_FILE = "data/authenticated_orcids.csv"


def _load_rows(path: str) -> list[tuple[str, str]]:
    """Lit le CSV `email,orcid` (sans en-tête). Ignore les lignes vides."""
    rows: list[tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for record in csv.reader(f):
            if len(record) < 2 or not record[0].strip():
                continue
            rows.append((record[0].strip(), record[1].strip()))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file", default=_DEFAULT_FILE, help=f"Chemin du CSV (défaut {_DEFAULT_FILE})."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="N'écrit rien : affiche le plan et sort."
    )
    args = parser.parse_args()

    rows = _load_rows(args.file)
    log.info("Lignes lues : %d (%s)", len(rows), args.file)

    engine = get_sync_engine()
    with engine.connect() as conn:
        # Résolution email → person_id (via persons_rh), insensible à la casse.
        email_to_persons: dict[str, list[int]] = {}
        for r in conn.execute(
            text(
                "SELECT lower(email) AS email, array_agg(DISTINCT person_id) AS pids "
                "FROM persons_rh WHERE email IS NOT NULL GROUP BY lower(email)"
            )
        ):
            email_to_persons[r.email] = list(r.pids)

        # État courant des ORCID du fichier, pour prévoir l'issue et détecter les déplacements.
        entries: list[tuple[int, str]] = []
        malformed: list[str] = []
        unmatched: list[str] = []
        ambiguous: list[str] = []
        for raw_email, raw_orcid in rows:
            orcid = normalize_orcid(raw_orcid)
            if orcid is None:
                malformed.append(f"{raw_email} → {raw_orcid!r}")
                continue
            persons = email_to_persons.get(raw_email.lower())
            if not persons:
                unmatched.append(raw_email)
                continue
            if len(persons) > 1:
                ambiguous.append(f"{raw_email} → {persons}")
                continue
            entries.append((persons[0], orcid))

        # Déplacements à venir : ORCID actuellement sur une autre personne.
        current = {
            r.id_value: (r.person_id, r.status)
            for r in conn.execute(
                text(
                    "SELECT id_value, person_id, CAST(status AS text) AS status "
                    "FROM person_identifiers WHERE id_type = 'orcid' AND id_value = ANY(:v)"
                ),
                {"v": [o for _, o in entries]},
            )
        }
        reassignments = [
            (orcid, current[orcid][0], person_id)
            for person_id, orcid in entries
            if orcid in current and current[orcid][0] != person_id
        ]

    if malformed:
        log.warning("ORCID malformés ignorés : %d", len(malformed))
        for m in malformed:
            log.warning("  malformé : %s", m)
    if unmatched:
        log.warning("Emails sans personne RH (ignorés) : %d", len(unmatched))
        for e in unmatched:
            log.warning("  inconnu : %s", e)
    if ambiguous:
        log.warning("Emails rattachés à plusieurs personnes (ignorés) : %d", len(ambiguous))
        for a in ambiguous:
            log.warning("  ambigu : %s", a)
    if reassignments:
        log.warning(
            "ORCID à déplacer vers la personne authentifiée (doublons probables à fusionner) : %d",
            len(reassignments),
        )
        for orcid, from_pid, to_pid in reassignments:
            log.warning("  déplacement : %s  personne %d → %d", orcid, from_pid, to_pid)

    log.info("À authentifier (email résolu) : %d", len(entries))

    if not entries:
        log.info("Rien à faire.")
        return 0
    if args.dry_run:
        log.info("Dry-run : aucune écriture.")
        return 0

    with engine.begin() as conn:
        repo = person_repository(conn)
        outcomes = import_authenticated_orcids(entries, repo=repo)

    log.info(
        "✓ Terminé — insérés %d, renforcés %d, déplacés %d, inchangés %d.",
        outcomes.get("inserted", 0),
        outcomes.get("upgraded", 0),
        outcomes.get("reassigned", 0),
        outcomes.get("noop", 0),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
