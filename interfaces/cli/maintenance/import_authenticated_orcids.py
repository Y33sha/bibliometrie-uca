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
from pathlib import Path

from application.ports.repositories.person_repository import AuthenticateOrcidOutcome
from application.services.persons.core import authenticate_orcids
from domain.persons.identifiers import normalize_orcid
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.repositories import person_repository

log = setup_logger("import_authenticated_orcids", os.path.dirname(__file__))

# `parents[3]` remonte interfaces/cli/maintenance/ → racine du dépôt ; le fichier vit sous data/.
_DEFAULT_FILE = Path(__file__).resolve().parents[3] / "data" / "authenticated_orcids.csv"


def _load_rows(path: str | Path) -> list[tuple[str, str]]:
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
        repo = person_repository(conn)
        email_to_persons = repo.map_rh_emails_to_person_ids()

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

        current = repo.find_identifier_holders("orcid", [o for _, o in entries])
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
        outcomes = authenticate_orcids(entries, repo=repo)

    log.info(
        "✓ Terminé — insérés %d, renforcés %d, déplacés %d, inchangés %d.",
        outcomes[AuthenticateOrcidOutcome.INSERTED],
        outcomes[AuthenticateOrcidOutcome.UPGRADED],
        outcomes[AuthenticateOrcidOutcome.REASSIGNED],
        outcomes[AuthenticateOrcidOutcome.NOOP],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
