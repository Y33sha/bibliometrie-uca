# STATUS: recurring (imports)
"""Import des personnes depuis un export RH (CSV ou TSV).

Usage :
    uv run python -m interfaces.cli.imports.import_persons export_rh.csv
    uv run python -m interfaces.cli.imports.import_persons export_rh.csv --dry-run
    uv run python -m interfaces.cli.imports.import_persons export_rh.tsv --export-date 2026-01-15

Les en-têtes sont sur la première ligne qui nomme le nom et le prénom. Les lignes au-dessus donnent la fenêtre d'observation de l'export (« Date début d'observation : », « Date fin d'observation : » ou « Date d'observation : »), à défaut `--export-date`. Colonnes reconnues : `SCALAR_COLUMNS` et `UNIT_COLUMNS`.

Un agent se rattache à une fiche `hr_records` par son matricule, à défaut par son email. Sinon, l'import ajoute la fiche à l'unique homonyme sans fiche RH (`_unique_homonym_without_record`), à défaut crée la personne et sa fiche. Les attributs de la fiche prennent les valeurs non vides de l'export. Les périodes de présence suivent `updated_periods`. L'import refuse un export antérieur au dernier importé.
"""

import argparse
import csv
import os
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum

from sqlalchemy import Connection, text

from domain.normalize import normalize_text, optional_plain_text
from domain.persons.hr_periods import HrPeriod, merge_periods, updated_periods
from domain.persons.name_matching import is_full_first_name
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from infrastructure.read_models.perimeters.queries import (
    get_perimeter_structure_ids,
    persons_perimeter_code,
)
from infrastructure.repositories import person_repository
from pipeline.transformation.structures.name_recognition import StructureNameMatcher

log = setup_logger("import_persons", os.path.dirname(__file__))


# Noms reconnus de chaque colonne propre à l'agent, du plus spécifique au plus général.
SCALAR_COLUMNS: dict[str, tuple[str, ...]] = {
    "siham_id": ("matricule siham", "matricule"),
    "last_name": ("nom usuel - individu", "nom", "last_name", "lastname", "name", "family_name"),
    "first_name": (
        "prénom - individu",
        "prenom",
        "prénom",
        "first_name",
        "firstname",
        "given_name",
    ),
    "email": ("_mail", "email", "mail", "e-mail", "courriel"),
    "staff_category": ("_ens/biatss", "catégorie", "categorie"),
    "employment_status": ("statut",),
    "corps": ("corps", "corps ou statut"),
    "grade": ("grade",),
}


@dataclass(frozen=True)
class UnitColumns:
    """Noms reconnus des colonnes d'une affectation datée : libellé de l'unité, début, fin."""

    label: tuple[str, ...]
    start: tuple[str, ...]
    end: tuple[str, ...]


UNIT_COLUMNS = (
    UnitColumns(
        label=("unité organisationnelle (lib abr) - répartition organisationnelle",),
        start=("date d'effet - répartition organisationnelle",),
        end=("date de fin - répartition organisationnelle",),
    ),
    UnitColumns(
        label=(
            "unité organisationnelle (lib abr) - principales/hiérarchique",
            "department-name",
            "departement",
            "département",
            "department",
            "labo",
            "laboratoire",
            "composante",
            "unit",
        ),
        start=(
            "date d'effet - principales/hiérarchique",
            "date de début dans le corps ou début de contrat",
            "start-date",
            "date_debut",
            "début",
            "debut",
            "date_arrivee",
            "arrivee",
        ),
        end=(
            "date de fin - principales/hiérarchique",
            "date de fin dans le corps ou début de contrat",
            "end-date",
            "date_fin",
            "fin",
            "date_depart",
            "depart",
        ),
    ),
)

_WINDOW_START = re.compile(r"Date (?:début d'observation|d'observation)\s*:\s*(\d{2}/\d{2}/\d{4})")
_WINDOW_END = re.compile(r"Date (?:fin d'observation|d'observation)\s*:\s*(\d{2}/\d{2}/\d{4})")
_HEADER_SEARCH_ROWS = 20


@dataclass(frozen=True)
class HrRow:
    """Agent d'un export RH : identité, attributs, périodes de présence."""

    last_name: str
    first_name: str
    siham_id: str | None = None
    email: str | None = None
    staff_category: str | None = None
    employment_status: str | None = None
    corps: str | None = None
    grade: str | None = None
    periods: tuple[HrPeriod, ...] = ()


@dataclass(frozen=True)
class HrExport:
    """Export RH : fenêtre d'observation et lignes."""

    window_start: date | None
    window_end: date | None
    rows: list[HrRow]


def parse_date(val: object) -> date | None:
    """Lit une date dans l'un des formats reconnus."""
    if not val or str(val).strip() == "":
        return None
    val = str(val).strip()
    # Des dates sans heure : le fuseau n'entre ni dans leur lecture ni dans leur arithmétique.
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(val, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    # Date sérialisée par Excel : nombre de jours depuis le 1899-12-30, base décalée d'un jour pour compenser le faux 29 février 1900 d'Excel.
    try:
        n = int(float(val))
        if 30000 < n < 60000:
            return date(1899, 12, 30) + timedelta(days=n)
    except ValueError, OverflowError:
        pass
    log.warning("Date non parsable: '%s'", val)
    return None


def _normalize_header(header: str) -> str:
    return header.lower().strip().replace(" ", "_").replace("-", "_")


def _find_column(headers: Sequence[str], aliases: Iterable[str]) -> int | None:
    """Renvoie l'indice de la première colonne nommée par l'un des alias, dans l'ordre des alias."""
    normalized = [_normalize_header(h) for h in headers]
    for alias in aliases:
        name = _normalize_header(alias)
        if name in normalized:
            return normalized.index(name)
    return None


def _scalar_columns(headers: Sequence[str]) -> dict[str, int]:
    found = {field: _find_column(headers, aliases) for field, aliases in SCALAR_COLUMNS.items()}
    return {field: idx for field, idx in found.items() if idx is not None}


def _header_index(rows: Sequence[Sequence[str]]) -> int | None:
    for i, row in enumerate(rows[:_HEADER_SEARCH_ROWS]):
        columns = _scalar_columns(row)
        if "last_name" in columns and "first_name" in columns:
            return i
    return None


def _cell(row: Sequence[str], idx: int | None) -> str | None:
    # Mise à plat comme sur les champs moissonnés : un export RH transite par un tableur, d'où des espaces insécables et, sur les cellules recopiées depuis une page web, du balisage et des entités HTML.
    return optional_plain_text(row[idx]) if idx is not None and idx < len(row) else None


def parse_rows(rows: Sequence[Sequence[str]]) -> HrExport:
    """Lit un export RH déjà découpé en cellules.

    Raises:
        ValueError: aucune ligne d'en-têtes ne nomme le nom et le prénom.
    """
    header_index = _header_index(rows)
    if header_index is None:
        raise ValueError("En-têtes introuvables : aucune ligne ne nomme le nom et le prénom.")
    headers = rows[header_index]
    scalars = _scalar_columns(headers)
    units = [
        (
            _find_column(headers, u.label),
            _find_column(headers, u.start),
            _find_column(headers, u.end),
        )
        for u in UNIT_COLUMNS
    ]
    log.info("Colonnes détectées : %s, unités : %s", scalars, units)

    preamble = " ".join(cell for row in rows[:header_index] for cell in row)
    starts, ends = _WINDOW_START.search(preamble), _WINDOW_END.search(preamble)

    parsed = []
    for row in rows[header_index + 1 :]:
        values = {field: _cell(row, idx) for field, idx in scalars.items()}
        last_name, first_name = values.pop("last_name"), values.pop("first_name")
        if not last_name or not first_name:
            continue
        periods = tuple(
            HrPeriod(label, parse_date(_cell(row, start)), parse_date(_cell(row, end)))
            for label_idx, start, end in units
            if (label := _cell(row, label_idx))
        )
        parsed.append(HrRow(last_name, first_name, periods=periods, **values))
    return HrExport(
        window_start=parse_date(starts.group(1)) if starts else None,
        window_end=parse_date(ends.group(1)) if ends else None,
        rows=parsed,
    )


def read_export(filepath: str) -> HrExport:
    """Lit un export RH CSV ou TSV. Le séparateur retenu est le premier qui fait apparaître la ligne d'en-têtes."""
    with open(filepath, encoding="utf-8-sig") as f:
        content = f.read()
    try:
        sniffed = [csv.Sniffer().sniff(content[:4096], delimiters=",;\t|").delimiter]
    except csv.Error:
        sniffed = []
    for delimiter in [*sniffed, ",", ";", "\t"]:
        rows = list(csv.reader(content.splitlines(keepends=True), delimiter=delimiter))
        if _header_index(rows) is not None:
            return parse_rows(rows)
    raise ValueError(
        f"En-têtes introuvables dans {filepath} : aucune ligne ne nomme le nom et le prénom."
    )


def _agent_key(row: HrRow) -> str | None:
    if row.siham_id:
        return f"siham:{row.siham_id}"
    if row.email:
        return f"email:{row.email.lower()}"
    return None


def group_agents(rows: Iterable[HrRow]) -> tuple[list[HrRow], int]:
    """Réunit les lignes d'un même agent (matricule, à défaut email). Renvoie les agents et le nombre de lignes sans matricule ni email, écartées.

    Les attributs viennent de la ligne de période la plus récente. Les périodes de l'agent fusionnent par unité.
    """
    by_key: dict[str, list[HrRow]] = {}
    unkeyed = 0
    for row in rows:
        key = _agent_key(row)
        if key is None:
            unkeyed += 1
            continue
        by_key.setdefault(key, []).append(row)
    agents = []
    for agent_rows in by_key.values():
        latest = max(
            agent_rows,
            key=lambda r: max((p.start or date.min for p in r.periods), default=date.min),
        )
        periods = merge_periods(p for r in agent_rows for p in r.periods)
        agents.append(replace(latest, periods=tuple(periods)))
    return agents, unkeyed


class UnitStructures:
    """Correspondance des libellés d'unité avec `structures` : nom ou sigle identique, à défaut reconnaissance des structures, avec le périmètre des personnes pour contexte.

    Les racines du périmètre sont écartées du résultat : un libellé qui les cite désigne une unité de l'établissement.
    """

    def __init__(self, conn: Connection) -> None:
        self._by_name: dict[str, set[int]] = {}
        for r in conn.execute(text("SELECT id, name, acronym FROM structures")):
            for value in (r.name, r.acronym):
                if value:
                    self._by_name.setdefault(normalize_text(value), set()).add(r.id)
        self._matcher = StructureNameMatcher.load(conn)
        code = persons_perimeter_code(conn)
        self._context = frozenset(get_perimeter_structure_ids(conn, code)) if code else frozenset()
        roots = conn.execute(
            text("SELECT root_structure_ids FROM perimeters WHERE code = :code"), {"code": code}
        ).scalar()
        self._roots = frozenset(roots or ())
        self._cache: dict[str, int | None] = {}
        self.unmatched: set[str] = set()
        self.ambiguous: set[str] = set()

    def structure_id(self, label: str) -> int | None:
        if label not in self._cache:
            self._cache[label] = self._resolve(label)
        return self._cache[label]

    def _resolve(self, label: str) -> int | None:
        normalized = normalize_text(label)
        exact = self._by_name.get(normalized, set())
        if len(exact) == 1:
            return next(iter(exact))
        recognized = {
            m.structure_id for m in self._matcher.resolve(normalized, self._context)
        } - self._roots
        if len(recognized) == 1:
            return next(iter(recognized))
        (self.ambiguous if recognized else self.unmatched).add(label)
        return None


class RhImportOutcome(StrEnum):
    """Issue de l'import d'un agent par `import_agent`."""

    CREATED = "created"  # personne et fiche RH créées
    BY_SIHAM_ID = "by_siham_id"  # fiche rattachée par le matricule
    BY_EMAIL = "by_email"  # fiche rattachée par l'email
    BY_NAME = "by_name"  # fiche ajoutée à l'unique homonyme, sans fiche RH


_BY_SIHAM_ID = text("SELECT person_id FROM hr_records WHERE siham_id = :siham_id")

_BY_EMAIL = text("""
    SELECT person_id FROM hr_records
    WHERE lower(email) = lower(:email) AND (siham_id IS NULL OR CAST(:siham_id AS text) IS NULL)
""")

_HOMONYMS = text("""
    SELECT p.id, p.exclusion, EXISTS (SELECT 1 FROM hr_records r WHERE r.person_id = p.id) AS has_record
    FROM persons p
    WHERE p.last_name_normalized = :last_name AND p.first_name_normalized = :first_name
""")

_UPDATE_RECORD = text("""
    UPDATE hr_records SET
        siham_id = coalesce(:siham_id, siham_id),
        email = coalesce(:email, email),
        staff_category = coalesce(:staff_category, staff_category),
        employment_status = coalesce(:employment_status, employment_status),
        corps = coalesce(:corps, corps),
        grade = coalesce(:grade, grade),
        hr_export_date = coalesce(:export_date, hr_export_date)
    WHERE person_id = :person_id
""")

_INSERT_RECORD = text("""
    INSERT INTO hr_records
        (person_id, siham_id, email, staff_category, employment_status, corps, grade, hr_export_date)
    VALUES
        (:person_id, :siham_id, :email, :staff_category, :employment_status, :corps, :grade, :export_date)
""")

_INSERT_PERIOD = text("""
    INSERT INTO hr_periods (person_id, unit_label, structure_id, start_date, end_date)
    VALUES (:person_id, :unit_label, :structure_id, :start_date, :end_date)
""")


def _find_record(conn: Connection, agent: HrRow) -> tuple[int, RhImportOutcome] | None:
    if agent.siham_id:
        person_id = conn.execute(_BY_SIHAM_ID, {"siham_id": agent.siham_id}).scalar()
        if person_id is not None:
            return person_id, RhImportOutcome.BY_SIHAM_ID
    if agent.email:
        person_id = conn.execute(
            _BY_EMAIL, {"email": agent.email, "siham_id": agent.siham_id}
        ).scalar()
        if person_id is not None:
            return person_id, RhImportOutcome.BY_EMAIL
    return None


def _unique_homonym_without_record(conn: Connection, agent: HrRow) -> int | None:
    """Renvoie l'unique personne de même nom et même prénom que l'agent, quand elle est sans fiche RH ni exclusion. Le prénom est complet, sans initiale."""
    if not is_full_first_name(agent.first_name):
        return None
    homonyms = conn.execute(
        _HOMONYMS,
        {
            "last_name": normalize_text(agent.last_name),
            "first_name": normalize_text(agent.first_name),
        },
    ).all()
    if len(homonyms) != 1:
        return None
    [homonym] = homonyms
    return None if homonym.has_record or homonym.exclusion else homonym.id


def import_agent(
    conn: Connection,
    agent: HrRow,
    units: UnitStructures,
    *,
    window_start: date | None,
    export_date: date | None,
) -> RhImportOutcome:
    """Rattache l'agent à sa fiche RH, à défaut ajoute la fiche à son unique homonyme ou crée la personne. Met à jour ses attributs et ses périodes de présence."""
    attributes = {
        "siham_id": agent.siham_id,
        "email": agent.email,
        "staff_category": agent.staff_category,
        "employment_status": agent.employment_status,
        "corps": agent.corps,
        "grade": agent.grade,
        "export_date": export_date,
    }
    found = _find_record(conn, agent)
    if found is None:
        homonym = _unique_homonym_without_record(conn, agent)
        if homonym is None:
            person_id = person_repository(conn).create(agent.last_name, agent.first_name)
            outcome = RhImportOutcome.CREATED
        else:
            person_id, outcome = homonym, RhImportOutcome.BY_NAME
        conn.execute(_INSERT_RECORD, {"person_id": person_id, **attributes})
    else:
        person_id, outcome = found
        conn.execute(_UPDATE_RECORD, {"person_id": person_id, **attributes})

    stored = [
        HrPeriod(r.unit_label, r.start_date, r.end_date)
        for r in conn.execute(
            text("SELECT unit_label, start_date, end_date FROM hr_periods WHERE person_id = :p"),
            {"p": person_id},
        )
    ]
    periods = (
        updated_periods(stored, agent.periods, window_start)
        if window_start
        else merge_periods([*stored, *agent.periods])
    )
    conn.execute(text("DELETE FROM hr_periods WHERE person_id = :p"), {"p": person_id})
    for period in periods:
        conn.execute(
            _INSERT_PERIOD,
            {
                "person_id": person_id,
                "unit_label": period.unit_label,
                "structure_id": units.structure_id(period.unit_label),
                "start_date": period.start,
                "end_date": period.end,
            },
        )
    return outcome


class OlderExportError(ValueError):
    """Export antérieur au dernier export importé."""


def import_export(conn: Connection, export: HrExport) -> dict[RhImportOutcome, int]:
    """Importe les agents d'un export RH. Renvoie le nombre d'agents par issue. L'appelant commite.

    Raises:
        OlderExportError: l'export est antérieur au dernier importé.
    """
    last_export = conn.execute(text("SELECT max(hr_export_date) FROM hr_records")).scalar()
    if export.window_end and last_export and export.window_end < last_export:
        raise OlderExportError(
            f"Export du {export.window_end} antérieur au dernier importé ({last_export})."
        )
    agents, unkeyed = group_agents(export.rows)
    if unkeyed:
        log.warning("  %s lignes sans matricule ni email, écartées", unkeyed)
    units = UnitStructures(conn)
    counts = dict.fromkeys(RhImportOutcome, 0)
    for agent in agents:
        outcome = import_agent(
            conn, agent, units, window_start=export.window_start, export_date=export.window_end
        )
        counts[outcome] += 1
    for label in sorted(units.unmatched):
        log.info("  Unité sans structure : %s", label)
    for label in sorted(units.ambiguous):
        log.warning("  Unité à plusieurs structures reconnues : %s", label)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Import personnes RH → base")
    parser.add_argument("file", help="Export RH (CSV ou TSV)")
    parser.add_argument(
        "--export-date",
        type=str,
        default=None,
        help="Date de l'export (YYYY-MM-DD), pour un fichier sans fenêtre d'observation",
    )
    parser.add_argument("--dry-run", action="store_true", help="Importer puis annuler")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        log.error("Fichier introuvable: %s", args.file)
        sys.exit(1)

    export = read_export(args.file)
    if export.window_end is None:
        if args.export_date is None:
            log.error("Fenêtre d'observation absente du fichier : préciser --export-date.")
            sys.exit(1)
        export_date = parse_date(args.export_date)
        export = HrExport(export_date, export_date, export.rows)
    log.info(
        "=== Import de %s : %s lignes, fenêtre du %s au %s ===",
        args.file,
        len(export.rows),
        export.window_start,
        export.window_end,
    )

    with get_sync_engine().begin() as conn:
        try:
            counts = import_export(conn, export)
        except OlderExportError as e:
            log.error(str(e))
            sys.exit(1)
        log.info(
            "=== %s personnes créées, %s fiches ajoutées à un homonyme, "
            "%s fiches rattachées par matricule, %s par email ===",
            counts[RhImportOutcome.CREATED],
            counts[RhImportOutcome.BY_NAME],
            counts[RhImportOutcome.BY_SIHAM_ID],
            counts[RhImportOutcome.BY_EMAIL],
        )
        if args.dry_run:
            conn.rollback()
            log.info("(dry-run, rien d'écrit)")


if __name__ == "__main__":
    main()
