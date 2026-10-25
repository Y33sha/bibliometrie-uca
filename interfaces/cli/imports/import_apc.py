# STATUS: recurring (imports)
"""Importe un fichier de frais de publication dans `apc_payments`.

Trois formats, reconnus aux colonnes du fichier :

- le jeu de données Open APC (frais d'open access) ;
- le fichier « frais hors OA » de l'enquête nationale (autres frais de publication) ;
- la réponse d'un établissement à l'enquête APC, export CSV de sa feuille de paiements. Ses montants négatifs annulent un paiement.

Sont importés les paiements dont le DOI désigne une publication de la base. Avec `--institution`, les paiements à DOI de l'établissement désigné le sont aussi, sans publication ; ils la rejoignent quand elle entre dans la base. Un paiement déjà présent, même DOI, même payeur, même montant et même type de frais, reste tel quel : le script se rejoue sans créer de doublon.

Le laboratoire et le payeur sont rattachés à leur structure par les formes de noms des structures, comme les adresses d'affiliation. Le script liste les libellés sans structure.

La réponse d'un établissement à l'enquête l'emporte sur OpenAPC : un frais d'open access OpenAPC d'un article que la réponse de son payeur décrit déjà est retiré (`drop_open_apc_superseded_by_institution`).

Usage :
    python -m interfaces.cli.imports.import_apc data/apc/apc_de.csv --institution "Université Clermont Auvergne"
    python -m interfaces.cli.imports.import_apc "data/FPhorsOA … .csv" --institution 200 --dry-run
    python -m interfaces.cli.imports.import_apc "data/apc/APC_2025_… .csv"
"""

import argparse
import csv
import os
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import Connection, text

from domain.normalize import normalize_text, sanitize_optional_text
from domain.publications.identifiers import clean_doi
from domain.structures.identifiers import RorId
from domain.structures.structure import StructureType
from domain.types import JsonValue
from infrastructure.db.engine import get_sync_engine
from infrastructure.observability.log import setup_logger
from pipeline.transformation.structures.name_recognition import (
    MatchableNameForm,
    StructureNameMatcher,
    load_name_forms,
)

log = setup_logger("import_apc", os.path.dirname(__file__))

type Payment = dict[str, JsonValue]


class FileFormat(StrEnum):
    """Format d'un fichier de frais de publication."""

    OPEN_APC = "open_apc"
    NON_OA_FEES = "non_oa_fees"
    INSTITUTION_SURVEY = "institution_survey"


# Colonne propre à chaque format, qui le désigne.
_FORMAT_MARKERS = {
    "euro": FileFormat.OPEN_APC,
    "Montant payé en EURHT": FileFormat.NON_OA_FEES,
    "montant_euros_ht": FileFormat.INSTITUTION_SURVEY,
}

# Titres de section de la réponse d'un établissement à l'enquête APC, dans la colonne du laboratoire.
_NON_OA_FEES_SECTION = "Pas d'APC"
_REJECTED_SECTION = "Retour Couperin"

_INSERT = text("""
    INSERT INTO apc_payments (
        doi, amount_eur_ht, billing_year, publication_year, publisher_name, journal_name, issn,
        institution, budget, coman_id, lab_name, remarks, open_access_fee,
        source_file, publication_id
    ) VALUES (
        :doi, :amount_eur_ht, :billing_year, :publication_year, :publisher_name, :journal_name, :issn,
        :institution, :budget, :coman_id, :lab_name, :remarks, :open_access_fee,
        :source_file, :publication_id
    )
    ON CONFLICT ON CONSTRAINT apc_payments_payment_key DO NOTHING
    RETURNING id
""")


def clean(cell: str | None) -> str | None:
    """Met la cellule à plat — balises, entités HTML et caractères invisibles retirés — et rend None si elle est vide."""
    return sanitize_optional_text(cell)


def parse_amount(cell: str | None) -> float | None:
    """Montant en euros, au format français (espaces, virgule décimale) ou anglais. None faute de valeur lisible."""
    value = (cell or "").replace("\xa0", "").replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return round(float(value), 2)
    except ValueError:
        return None


def parse_year(cell: str | None) -> int | None:
    """Année entre 1990 et 2100, ou None."""
    value = (cell or "").strip()
    if not value.isdigit():
        return None
    year = int(value)
    return year if 1990 <= year <= 2100 else None


def detect_format(columns: list[str]) -> FileFormat:
    """Format d'un fichier, d'après ses colonnes. Lève `ValueError` pour un fichier d'un autre format."""
    for marker, file_format in _FORMAT_MARKERS.items():
        if marker in columns:
            return file_format
    raise ValueError(
        "Format inconnu : ni fichier Open APC, ni fichier des frais hors OA, ni réponse d'établissement à l'enquête APC"
    )


def open_apc_payment(row: Mapping[str, str]) -> Payment:
    """Paiement d'une ligne Open APC.

    La période déclarée tient lieu d'année de facturation et de publication. L'ISSN retenu est celui de la revue, à défaut son ISSN de liaison. La mention `hybrid` signale une revue sur abonnement dont cet article est ouvert.
    """
    period = parse_year(row.get("period"))
    return {
        "doi": clean_doi(row.get("doi")),
        "amount_eur_ht": parse_amount(row.get("euro")),
        "billing_year": period,
        "publication_year": period,
        "publisher_name": clean(row.get("publisher")),
        "journal_name": clean(row.get("journal_full_title")),
        "issn": clean(row.get("issn")) or clean(row.get("issn_l")),
        "institution": clean(row.get("institution")),
        "budget": None,
        "coman_id": None,
        "lab_name": None,
        "remarks": "hybrid" if (row.get("is_hybrid") or "").upper() == "TRUE" else None,
        "open_access_fee": True,
    }


def non_oa_fee_payment(row: Mapping[str, str]) -> Payment:
    """Paiement d'une ligne du fichier des frais hors OA. Le payeur est la colonne « Budget »."""
    coman_id = (row.get("CoMan Id.") or "").strip()
    budget = clean(row.get("Budget"))
    return {
        "doi": clean_doi(row.get("DOI")),
        "amount_eur_ht": parse_amount(row.get("Montant payé en EURHT")),
        "billing_year": parse_year(row.get("Année de facturation")),
        "publication_year": parse_year(row.get("Année de publication")),
        "publisher_name": clean(row.get("Editeur")),
        "journal_name": clean(row.get("Revue")),
        "issn": clean(row.get("ISSN")),
        "institution": budget,
        "budget": budget,
        "coman_id": int(coman_id) if coman_id.isdigit() else None,
        "lab_name": clean(row.get("Laboratoire")),
        "remarks": clean(row.get("Remarques")),
        "open_access_fee": False,
    }


def institution_survey_payment(row: Mapping[str, str], *, open_access_fee: bool) -> Payment:
    """Paiement d'une ligne de la réponse d'un établissement à l'enquête APC.

    Le payeur est désigné par son ROR (`payer_ror`), nommé à l'import. La remarque réunit le commentaire de l'établissement et la réponse de Couperin.
    """
    ror = RorId.try_parse(row.get("ror"))
    couperin = clean(row.get("Réponse Couperin"))
    remarks = [clean(row.get("commentaire")), f"Couperin : {couperin}" if couperin else None]
    return {
        "doi": clean_doi(row.get("doi")),
        "amount_eur_ht": parse_amount(row.get("montant_euros_ht")),
        "billing_year": parse_year(row.get("année_facturation")),
        "publication_year": None,
        "publisher_name": None,
        "journal_name": None,
        "issn": None,
        "institution": None,
        "payer_ror": ror.value if ror else None,
        "budget": clean(row.get("budget")),
        "coman_id": None,
        "lab_name": clean(row.get("laboratoire_sigle")),
        "remarks": " — ".join(r for r in remarks if r) or None,
        "open_access_fee": open_access_fee,
    }


def institution_survey_payments(rows: Iterable[Mapping[str, str]]) -> list[Payment]:
    """Paiements de la réponse d'un établissement à l'enquête APC.

    Les lignes qui suivent le titre « Pas d'APC… » sont des frais hors open access. Celles qui suivent « Retour Couperin » sont écartées par Couperin et ignorées. Une ligne sans laboratoire, comme le total, est ignorée.
    """
    payments: list[Payment] = []
    open_access_fee = True
    for row in rows:
        lab = (row.get("laboratoire_sigle") or "").strip()
        if lab.startswith(_REJECTED_SECTION):
            break
        if lab.startswith(_NON_OA_FEES_SECTION):
            open_access_fee = False
        elif lab:
            payments.append(institution_survey_payment(row, open_access_fee=open_access_fee))
    return cancel_refunds(payments)


def cancel_refunds(payments: list[Payment]) -> list[Payment]:
    """Retire les paiements annulés : chaque montant négatif annule un montant positif de même valeur, même DOI, même laboratoire, même type de frais."""
    refunds: Counter[tuple[JsonValue, ...]] = Counter()
    for p in payments:
        if isinstance(amount := p["amount_eur_ht"], float) and amount < 0:
            refunds[(p["doi"], p["lab_name"], p["open_access_fee"], -amount)] += 1
    kept: list[Payment] = []
    for p in payments:
        amount = p["amount_eur_ht"]
        if isinstance(amount, float) and amount < 0:
            continue
        key = (p["doi"], p["lab_name"], p["open_access_fee"], amount)
        if refunds[key]:
            refunds[key] -= 1
        else:
            kept.append(p)
    return kept


type PaymentFilter = Callable[[Payment], bool]


def institution_filter(file_format: FileFormat, institution: str) -> PaymentFilter:
    """Reconnaît les paiements de l'établissement désigné par `institution`, selon le format du fichier : son nom pour Open APC, son `coman_id` pour les frais hors OA, son ROR pour la réponse à l'enquête.

    Lève `ValueError` sur une valeur illisible pour le format.
    """
    if file_format is FileFormat.OPEN_APC:
        name = normalize_text(institution)
        return lambda p: normalize_text(str(p.get("institution") or "")) == name
    if file_format is FileFormat.NON_OA_FEES:
        if not institution.strip().isdigit():
            raise ValueError(
                f"coman_id attendu pour un fichier des frais hors OA : {institution!r}"
            )
        coman_id = int(institution)
        return lambda p: p.get("coman_id") == coman_id
    ror = RorId.try_parse(institution)
    if ror is None:
        raise ValueError(f"ROR attendu pour une réponse à l'enquête APC : {institution!r}")
    return lambda p: p.get("payer_ror") == ror.value


_MAPPERS: dict[FileFormat, Callable[[Mapping[str, str]], Payment]] = {
    FileFormat.OPEN_APC: open_apc_payment,
    FileFormat.NON_OA_FEES: non_oa_fee_payment,
}


def read_payments(path: Path) -> tuple[FileFormat, list[Payment]]:
    """Format du fichier et paiements de ses lignes. L'en-tête est la première ligne qui désigne un format : les lignes qui la précèdent sont ignorées."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        lines = [line for line in csv.reader(f) if any(cell.strip() for cell in line)]
    header_index = next(
        (i for i, line in enumerate(lines) if any(m in line for m in _FORMAT_MARKERS)), 0
    )
    header = lines[header_index] if lines else []
    file_format = detect_format(header)
    rows = [dict(zip(header, line, strict=False)) for line in lines[header_index + 1 :]]
    if file_format is FileFormat.INSTITUTION_SURVEY:
        return file_format, institution_survey_payments(rows)
    mapper = _MAPPERS[file_format]
    return file_format, [mapper(row) for row in rows]


LAB_TYPES = frozenset({StructureType.LABO})
PAYER_TYPES = frozenset(
    {StructureType.UNIVERSITE, StructureType.ECOLE, StructureType.ONR, StructureType.CHU}
)


class StructureResolver:
    """Structure désignée par un libellé, reconnue par ses formes de nom."""

    def __init__(self, forms: list[MatchableNameForm]) -> None:
        self._matcher = StructureNameMatcher(forms)
        self._types = {f.structure_id: f.structure_type for f in forms}

    def resolve(
        self, label: str, types: frozenset[StructureType], context: str | None = None
    ) -> int | None:
        """Seule structure reconnue dans `label` parmi les `types` donnés. None si aucune ou plusieurs.

        `context` : libellé lu avec `label`, qui satisfait les formes de noms valables seulement en présence d'une autre structure.
        """
        ids = {
            m.structure_id
            for m in self._matcher.resolve(normalize_text(f"{label} / {context or ''}"))
            if self._types[m.structure_id] in types
        }
        return ids.pop() if len(ids) == 1 else None


@dataclass(frozen=True, slots=True)
class UnresolvedLabel:
    """Libellé sans structure : colonne d'origine, texte, contexte, nombre de paiements."""

    column: str
    label: str
    context: str | None
    payments: int


# Colonne du libellé, colonne de son contexte, colonne de la structure, types de structure admis.
# Le payeur sert de contexte au laboratoire : il nomme souvent l'établissement de tutelle.
_LINKS = (
    ("lab_name", "institution", "lab_structure_id", LAB_TYPES),
    ("institution", "NULL::text", "budget_structure_id", PAYER_TYPES),
)


def map_structures(conn: Connection, resolver: StructureResolver) -> list[UnresolvedLabel]:
    """Rattache chaque paiement à son laboratoire et à son payeur, d'après leurs libellés.

    Recalcule tous les rattachements, donc reflète l'état courant des formes de noms. Rend les libellés sans structure, du plus fréquent au plus rare.
    """
    unresolved: list[UnresolvedLabel] = []
    for label_column, context_column, structure_column, types in _LINKS:
        counts = conn.execute(
            text(f"""
                SELECT {label_column} AS label, {context_column} AS context, count(*) AS n
                FROM apc_payments WHERE {label_column} IS NOT NULL GROUP BY 1, 2
            """)
        ).all()
        links = [
            {
                "label": r.label,
                "context": r.context,
                "sid": resolver.resolve(r.label, types, r.context),
            }
            for r in counts
        ]
        if links:
            conn.execute(
                text(f"""
                    UPDATE apc_payments SET {structure_column} = CAST(:sid AS integer)
                    WHERE {label_column} = :label
                      AND {context_column} IS NOT DISTINCT FROM CAST(:context AS text)
                      AND {structure_column} IS DISTINCT FROM CAST(:sid AS integer)
                """),
                links,
            )
        unresolved += [
            UnresolvedLabel(label_column, r.label, r.context, r.n)
            for r, link in zip(counts, links, strict=True)
            if link["sid"] is None
        ]
    return sorted(unresolved, key=lambda u: (u.column, -u.payments, u.label))


@dataclass(frozen=True, slots=True)
class ImportStats:
    """Bilan d'un import : lignes lues, lignes à DOI de la base, lignes à DOI de l'établissement hors de la base, paiements insérés, paiements OpenAPC retirés au profit d'une réponse d'établissement, libellés sans structure."""

    read: int
    in_base: int
    outside_base: int
    inserted: int
    superseded: int
    unresolved: list[UnresolvedLabel]


def import_payments(
    conn: Connection,
    payments: list[Payment],
    source_file: str,
    *,
    from_institution: PaymentFilter | None = None,
) -> ImportStats:
    """Insère les paiements dont le DOI désigne une publication de la base, puis rattache revues, éditeurs et structures.

    `from_institution` reconnaît les paiements de l'établissement : ceux qui ont un DOI absent de la base sont insérés sans publication.
    """
    payments = name_payers(conn, payments)
    publication_by_doi = {
        row.doi: row.id
        for row in conn.execute(
            text("SELECT lower(doi) AS doi, id FROM publications WHERE doi IS NOT NULL")
        )
    }
    in_base = [
        {**p, "source_file": source_file, "publication_id": publication_by_doi[doi]}
        for p in payments
        if isinstance(doi := p["doi"], str) and doi in publication_by_doi
    ]
    outside_base = [
        {**p, "source_file": source_file, "publication_id": None}
        for p in payments
        if from_institution is not None
        and isinstance(doi := p["doi"], str)
        and doi not in publication_by_doi
        and from_institution(p)
    ]
    inserted = sum(
        1 for p in in_base + outside_base if conn.execute(_INSERT, p).first() is not None
    )
    map_publications(conn)
    map_serials(conn)
    map_publishers(conn)
    resolver = StructureResolver(load_name_forms(conn))
    unresolved = map_structures(conn, resolver)
    superseded = drop_open_apc_superseded_by_institution(conn)
    return ImportStats(
        read=len(payments),
        in_base=len(in_base),
        outside_base=len(outside_base),
        inserted=inserted,
        superseded=superseded,
        unresolved=unresolved,
    )


def drop_open_apc_superseded_by_institution(conn: Connection) -> int:
    """Retire les frais d'open access OpenAPC d'un article que la réponse de son établissement payeur décrit déjà. Rend le nombre de paiements retirés.

    OpenAPC reprend les réponses à l'enquête sous une forme variable (lignes additionnées, première seule, ou toutes), que la clé d'unicité ne dédoublonne pas. La réponse de l'établissement, facturée ligne à ligne et rattachée au laboratoire, l'emporte. Un frais d'open access sans laboratoire vient d'OpenAPC, qui ne nomme pas le laboratoire ; avec laboratoire, il vient d'une réponse d'établissement. La règle vaut quel que soit l'ordre des imports.
    """
    return conn.execute(
        text("""
            DELETE FROM apc_payments oa
            WHERE oa.open_access_fee
              AND oa.lab_name IS NULL
              AND oa.doi IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM apc_payments r
                  WHERE r.open_access_fee
                    AND r.lab_name IS NOT NULL
                    AND r.doi = oa.doi
                    AND r.budget_structure_id = oa.budget_structure_id
              )
        """)
    ).rowcount


def name_payers(conn: Connection, payments: list[Payment]) -> list[Payment]:
    """Nomme le payeur désigné par son ROR, d'après le registre ROR. Un ROR absent du registre sert de nom."""
    rors = [ror for p in payments if isinstance(ror := p.get("payer_ror"), str)]
    if not rors:
        return payments
    names = {
        r.ror_id: r.name
        for r in conn.execute(
            text("SELECT ror_id, name FROM ror_organizations WHERE ror_id = ANY(:ids)"),
            {"ids": sorted(set(rors))},
        )
    }
    return [
        {**p, "institution": names.get(ror, ror)}
        if isinstance(ror := p.get("payer_ror"), str)
        else p
        for p in payments
    ]


def map_publications(conn: Connection) -> int:
    """Rattache à leur publication les paiements dont le DOI désigne une publication de la base."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET publication_id = p.id
            FROM publications p
            WHERE ap.doi IS NOT NULL
              AND ap.doi = lower(p.doi)
              AND ap.publication_id IS NULL
        """)
    ).rowcount


def map_serials(conn: Connection) -> int:
    """Rattache à leur revue les paiements dont l'ISSN désigne un ISSN actif d'une revue."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET serial_id = i.serial_id
            FROM serial_issns i
            WHERE ap.issn IS NOT NULL
              AND ap.issn = i.issn
              AND i.serial_id IS NOT NULL
              AND i.status = 'active'
              AND ap.serial_id IS NULL
        """)
    ).rowcount


def map_publishers(conn: Connection) -> int:
    """Rattache à leur éditeur les paiements dont le nom d'éditeur est celui d'un éditeur de la base."""
    return conn.execute(
        text("""
            UPDATE apc_payments ap
            SET publisher_id = pub.id
            FROM publishers pub
            WHERE ap.publisher_name IS NOT NULL
              AND lower(ap.publisher_name) = lower(pub.name)
              AND ap.publisher_id IS NULL
        """)
    ).rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description="Import d'un fichier de frais de publication")
    parser.add_argument("csv_file", type=Path, help="Fichier CSV d'un des trois formats")
    parser.add_argument("--dry-run", action="store_true", help="Compter sans écrire")
    parser.add_argument(
        "--institution",
        help="Établissement dont les paiements à DOI sont importés même hors de la base : "
        "son nom (Open APC), son coman_id (frais hors OA) ou son ROR (réponse à l'enquête)",
    )
    args = parser.parse_args()

    file_format, payments = read_payments(args.csv_file)
    log.info("%s : format %s, %d lignes", args.csv_file.name, file_format.value, len(payments))
    try:
        from_institution = (
            institution_filter(file_format, args.institution) if args.institution else None
        )
    except ValueError as e:
        parser.error(str(e))
    with get_sync_engine().connect() as conn:
        stats = import_payments(
            conn, payments, args.csv_file.name, from_institution=from_institution
        )
        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()
    log.info(
        "%d lignes à DOI de la base, %d lignes de l'établissement hors de la base, %d paiements %s",
        stats.in_base,
        stats.outside_base,
        stats.inserted,
        "à insérer (simulation)" if args.dry_run else "insérés",
    )
    if stats.superseded:
        log.info(
            "%d paiements OpenAPC retirés au profit de la réponse de l'établissement",
            stats.superseded,
        )
    for u in stats.unresolved:
        context = f" [{u.context}]" if u.context else ""
        log.info(
            "sans structure (%s) : %s%s — %d paiements", u.column, u.label, context, u.payments
        )


if __name__ == "__main__":
    main()
