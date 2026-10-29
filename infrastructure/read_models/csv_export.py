"""Écriture des exports CSV des listes : assainissement des cellules, plafond de lignes, rendu par blocs."""

import csv
import logging
from collections.abc import Iterable, Iterator, Sequence
from typing import cast

from sqlalchemy import Connection, Row, text

logger = logging.getLogger(__name__)

# Caractères par lesquels un tableur reconnaît le début d'une formule. Une cellule qui commence par l'un d'eux est évaluée à l'ouverture du fichier, avec le contenu qu'une source externe y a déposé : titres et noms de revues venus de HAL et d'OpenAlex.
_FORMULA_STARTERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize_formula(value: object) -> object:
    """Valeur préfixée d'une apostrophe si un tableur y lirait une formule, rendue intacte sinon.

    L'apostrophe marque la cellule comme texte et garde la valeur entière. Le test s'applique aussi à la valeur débarrassée de ses espaces de tête. Les valeurs non textuelles (année, montant) traversent sans préfixe et gardent leur type à la lecture.
    """
    if not isinstance(value, str):
        return value
    if value.startswith(_FORMULA_STARTERS) or value.lstrip().startswith(_FORMULA_STARTERS):
        return f"'{value}"
    return value


class _EchoStream:
    """Flux de sortie qui rend le texte écrit.

    `csv.writer` rend ce que son flux a rendu à l'écriture : branché là-dessus, `writerow` formate une ligne et la retourne.
    """

    def write(self, value: str) -> str:
        return value


# Marque d'ordre des octets, en tête du premier bloc : sans elle, un tableur lit l'UTF-8 comme de l'ANSI, et les accents ressortent en mojibake.
BOM = "﻿"


class CsvWriter:
    """Formateur de lignes CSV dont chaque cellule passe par `neutralize_formula`."""

    def __init__(self) -> None:
        self._writer = csv.writer(_EchoStream())

    def line(self, row: Iterable[object]) -> str:
        """Ligne CSV terminée par un saut de ligne, cellules assainies."""
        return cast("str", self._writer.writerow([neutralize_formula(cell) for cell in row]))

    def header(self, row: Iterable[object]) -> str:
        """Ligne d'en-tête, précédée de la marque d'ordre des octets."""
        return BOM + self.line(row)

    def truncation_notice(self, cap: int) -> str:
        """Dernière ligne disant que l'export s'arrête au plafond.

        Le fichier arrive par un lien de téléchargement, hors de toute page : cette ligne est le seul avertissement que reçoit le lecteur.
        """
        milliers = f"{cap:,}".replace(",", " ")
        return self.line(
            [f"— Export tronqué à {milliers} lignes : affiner les filtres pour l'obtenir entier."]
        )


# Taille visée d'un bloc rendu au client. Une ligne par bloc ferait des dizaines de milliers d'envois pour un export ; un bloc trop gros ramènerait le tampon que les blocs évitent.
EXPORT_CHUNK_SIZE = 64 * 1024


def chunked(lines: Iterator[str], size: int = EXPORT_CHUNK_SIZE) -> Iterator[str]:
    """Regroupe des lignes en blocs d'au moins `size` caractères, le dernier plus court."""
    pending: list[str] = []
    pending_size = 0
    for line in lines:
        pending.append(line)
        pending_size += len(line)
        if pending_size >= size:
            yield "".join(pending)
            pending.clear()
            pending_size = 0
    if pending:
        yield "".join(pending)


# Plafond de lignes d'un export : assez haut pour qu'un export légitime en reste loin, la requête et le fichier tenant en mémoire ; assez bas pour qu'une demande sans filtre, que n'importe qui peut répéter, laisse la mémoire disponible.
MAX_EXPORT_ROWS = 500_000


def cap_export_rows(
    rows: Sequence[Row[tuple[object, ...]]], cap: int
) -> tuple[Sequence[Row[tuple[object, ...]]], bool]:
    """Rend les lignes ramenées au plafond, et si la coupe a eu lieu.

    Les requêtes demandent `cap + 1` lignes : la ligne excédentaire signale le dépassement, sans `COUNT` séparé. La coupe suit le tri appliqué en base.
    """
    if len(rows) <= cap:
        return rows, False
    return rows[:cap], True


def fetch_export_rows(
    conn: Connection, sql: str, binds: dict[str, object], *, name: str
) -> tuple[Sequence[Row[tuple[object, ...]]], bool]:
    """Lignes d'un export, ramenées au plafond, et si la coupe a eu lieu.

    `sql` est une requête triée, sans clause LIMIT. `name` désigne l'export dans l'avertissement journalisé lors d'une coupe.
    """
    rows = conn.execute(
        text(f"{sql} LIMIT :export_limit"), {**binds, "export_limit": MAX_EXPORT_ROWS + 1}
    ).all()
    rows, truncated = cap_export_rows(rows, MAX_EXPORT_ROWS)
    if truncated:
        logger.warning("Export des %s tronqué au plafond de %d lignes", name, MAX_EXPORT_ROWS)
    return rows, truncated


def csv_chunks(
    header: Sequence[str], rows: Iterable[Sequence[object]], *, truncated: bool = False
) -> Iterator[str]:
    """Blocs d'un export CSV : l'en-tête, une ligne par élément de `rows`, puis l'avis de coupe si `truncated`."""

    def lines() -> Iterator[str]:
        writer = CsvWriter()
        yield writer.header(header)
        for row in rows:
            yield writer.line(row)
        if truncated:
            yield writer.truncation_notice(MAX_EXPORT_ROWS)

    return chunked(lines())
