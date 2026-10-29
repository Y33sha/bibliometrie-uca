# STATUS: maintenance
"""Importe les ORCID authentifiés par les chercheurs (fichier `data/authenticated_orcids.csv`).

Le fichier, sans en-tête, a une ligne `email,orcid` par chercheur : les ORCID que leur titulaire a authentifiés en se connectant à son compte ORCID. Chaque ligne rejoint la personne par son email (`hr_records.email`, sans égard à la casse) et reçoit le statut `authenticated`.

Cet import est le seul contexte autorisé à écrire ce statut : un trigger PostgreSQL (`protect_authenticated_identifier`) rejette toute autre écriture de `authenticated`, et interdit d'en dégrader un. L'authentification fait autorité sur l'attribution : un ORCID rattaché à une autre personne est déplacé vers celle de l'email. Chaque déplacement est signalé ; il révèle en général un doublon de personne à fusionner.

Réappliqué sur un fichier inchangé, l'import n'écrit rien.

Usage :
    python -m interfaces.cli.maintenance.import_authenticated_orcids [--file CHEMIN] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import os
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Connection, text

from domain.normalize import sanitize_optional_text
from domain.persons.identifiers import IdentifierOrigin, normalize_orcid
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger

log = setup_logger("import_authenticated_orcids", os.path.dirname(__file__))

# `parents[3]` remonte interfaces/cli/maintenance/ → racine du dépôt ; le fichier vit sous data/.
_DEFAULT_FILE = Path(__file__).resolve().parents[3] / "data" / "authenticated_orcids.csv"


def _load_rows(path: str | Path) -> list[tuple[str, str]]:
    """Lit le CSV `email,orcid` (sans en-tête). Ignore les lignes vides."""
    rows: list[tuple[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for record in csv.reader(f):
            if len(record) < 2:
                continue
            # Mise à plat des deux cellules : un fichier composé dans un tableur y glisse des espaces insécables et des caractères invisibles, qui feraient échouer en silence le rapprochement par email et la reconnaissance de l'ORCID.
            email = sanitize_optional_text(record[0])
            if not email:
                continue
            rows.append((email, sanitize_optional_text(record[1]) or ""))
    return rows


@dataclass(frozen=True, slots=True)
class AuthenticationPlan:
    """Ce que le fichier prescrit, une fois confronté aux personnes connues.

    `entries` contient les couples à authentifier ; les trois autres listes contiennent les lignes écartées, décrites pour le journal. Une ligne écartée n'est jamais une erreur du fichier seul : un email inconnu peut signaler un export RH en retard, et un email partagé par deux personnes, un doublon à fusionner.
    """

    entries: list[tuple[int, str]]
    malformed: list[str]
    unmatched: list[str]
    ambiguous: list[str]


def plan_authentications(
    rows: list[tuple[str, str]], email_to_persons: dict[str, list[int]]
) -> AuthenticationPlan:
    """Confronte les lignes du fichier aux personnes connues, et trie ce qui peut être authentifié.

    Trois raisons d'écarter une ligne : un ORCID que sa forme rend inexploitable, un email absent des fiches du personnel, un email partagé par plusieurs personnes, dont la personne visée est alors indécidable.
    """
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
    return AuthenticationPlan(entries, malformed, unmatched, ambiguous)


def find_reassignments(
    entries: list[tuple[int, str]], current: dict[str, tuple[int, str]]
) -> list[tuple[str, int, int]]:
    """ORCID détenus par une autre personne que celle qui l'a authentifié, et vers qui les déplacer.

    `current` associe chaque ORCID à son détenteur actuel (personne et statut), tel que le référentiel le renvoie. L'authentification fait autorité sur l'attribution : le déplacement a lieu. Chacun révèle en général un doublon de personne à fusionner, d'où leur signalement.
    """
    return [
        (orcid, current[orcid][0], person_id)
        for person_id, orcid in entries
        if orcid in current and current[orcid][0] != person_id
    ]


class AuthenticateOrcidOutcome(StrEnum):
    """Issue de l'authentification d'un ORCID par `authenticate_orcid`."""

    INSERTED = "inserted"  # l'ORCID n'existait pas, créé authentifié
    UPGRADED = "upgraded"  # déjà rattaché à cette personne, statut renforcé
    REASSIGNED = "reassigned"  # déplacé depuis une autre personne, puis authentifié
    NOOP = "noop"  # déjà authentifié sur cette personne


def rh_emails_to_person_ids(conn: Connection) -> dict[str, list[int]]:
    """`{email en minuscules: [person_id, ...]}` des fiches `hr_records` qui ont un email."""
    rows = conn.execute(
        text(
            "SELECT lower(email) AS email, array_agg(DISTINCT person_id) AS pids "
            "FROM hr_records WHERE email IS NOT NULL GROUP BY lower(email)"
        )
    )
    return {r.email: list(r.pids) for r in rows}


def orcid_holders(conn: Connection, orcids: list[str]) -> dict[str, tuple[int, str]]:
    """`{orcid: (person_id, statut)}` des ORCID donnés déjà présents en base."""
    rows = conn.execute(
        text(
            "SELECT id_value, person_id, CAST(status AS text) AS status "
            "FROM person_identifiers WHERE id_type = 'orcid' AND id_value = ANY(:v)"
        ),
        {"v": orcids},
    )
    return {r.id_value: (r.person_id, r.status) for r in rows}


def authenticate_orcid(conn: Connection, person_id: int, orcid: str) -> AuthenticateOrcidOutcome:
    """Pose le statut `authenticated` sur `orcid`, rattaché à `person_id`. Un ORCID d'une autre personne est déplacé."""
    existing = conn.execute(
        text(
            "SELECT id, person_id, CAST(status AS text) AS status "
            "FROM person_identifiers WHERE id_type = 'orcid' AND id_value = :v"
        ),
        {"v": orcid},
    ).first()
    if existing is None:
        conn.execute(
            text(
                "INSERT INTO person_identifiers (person_id, id_type, id_value, source, status) "
                "VALUES (:pid, 'orcid', :v, :src, 'authenticated')"
            ),
            {"pid": person_id, "v": orcid, "src": IdentifierOrigin.MANUAL.value},
        )
        return AuthenticateOrcidOutcome.INSERTED
    if existing.person_id == person_id and existing.status == "authenticated":
        return AuthenticateOrcidOutcome.NOOP
    outcome = (
        AuthenticateOrcidOutcome.REASSIGNED
        if existing.person_id != person_id
        else AuthenticateOrcidOutcome.UPGRADED
    )
    conn.execute(
        text(
            "UPDATE person_identifiers "
            "SET person_id = :pid, status = 'authenticated', source = :src "
            "WHERE id = :id"
        ),
        {"pid": person_id, "id": existing.id, "src": IdentifierOrigin.MANUAL.value},
    )
    return outcome


def authenticate_orcids(
    conn: Connection, entries: list[tuple[int, str]]
) -> Counter[AuthenticateOrcidOutcome]:
    """Authentifie les paires `(person_id, orcid)` et renvoie le décompte des issues.

    Le paramètre de session `app.orcid_authenticated_import` autorise l'écriture du statut, que le trigger `protect_authenticated_identifier` refuse ailleurs. `SET LOCAL` le borne à la transaction.
    """
    conn.execute(text("SET LOCAL app.orcid_authenticated_import = 'on'"))
    return Counter(authenticate_orcid(conn, person_id, orcid) for person_id, orcid in entries)


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
        plan = plan_authentications(rows, rh_emails_to_person_ids(conn))
        entries = plan.entries

        # État courant des ORCID du fichier, pour prévoir les déplacements.
        current = orcid_holders(conn, [o for _, o in entries])
        reassignments = find_reassignments(entries, current)

    if plan.malformed:
        log.warning("ORCID malformés ignorés : %d", len(plan.malformed))
        for m in plan.malformed:
            log.warning("  malformé : %s", m)
    if plan.unmatched:
        log.warning("Emails sans personne RH (ignorés) : %d", len(plan.unmatched))
        for e in plan.unmatched:
            log.warning("  inconnu : %s", e)
    if plan.ambiguous:
        log.warning("Emails rattachés à plusieurs personnes (ignorés) : %d", len(plan.ambiguous))
        for a in plan.ambiguous:
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
        outcomes = authenticate_orcids(conn, entries)

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
