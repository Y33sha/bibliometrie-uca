"""Écriture des exports CSV des listes : assainissement des cellules, plafond de lignes, rendu par blocs."""

import csv
import logging
from collections.abc import Iterable, Iterator, Sequence
from typing import cast

from sqlalchemy import Connection, Row, text

logger = logging.getLogger(__name__)

# Caractères de début de formule pour un tableur. Une cellule commençant par l'un d'eux est évaluée à l'ouverture du fichier. Son contenu vient de sources externes : titres et noms de revues de HAL et d'OpenAlex.
_FORMULA_STARTERS = ("=", "+", "-", "@", "\t", "\r")


def neutralize_formula(value: object) -> object:
    """Renvoie la valeur préfixée d'une apostrophe si un tableur y lirait une formule, intacte sinon.

    L'apostrophe marque la cellule comme texte et garde la valeur entière. Le test s'applique aussi à la valeur sans ses espaces de tête. Les valeurs non textuelles (année, montant) restent sans préfixe et gardent leur type à la lecture.
    """
    if not isinstance(value, str):
        return value
    if value.startswith(_FORMULA_STARTERS) or value.lstrip().startswith(_FORMULA_STARTERS):
        return f"'{value}"
    return value


class _EchoStream:
    """Flux de sortie qui renvoie le texte écrit.

    `csv.writer` renvoie la valeur renvoyée par son flux à l'écriture. Sur ce flux, `writerow` formate donc une ligne et la renvoie.
    """

    def write(self, value: str) -> str:
        return value


# Marque d'ordre des octets, en tête du premier bloc. Sans elle, un tableur lit l'UTF-8 comme de l'ANSI, et les accents s'affichent mal.
BOM = "﻿"


class CsvWriter:
    """Formateur de lignes CSV dont chaque cellule passe par `neutralize_formula`."""

    def __init__(self) -> None:
        self._writer = csv.writer(_EchoStream())

    def line(self, row: Iterable[object]) -> str:
        """Renvoie la ligne CSV, cellules assainies, terminée par un saut de ligne."""
        return cast("str", self._writer.writerow([neutralize_formula(cell) for cell in row]))

    def header(self, row: Iterable[object]) -> str:
        """Renvoie la ligne d'en-tête, précédée de la marque d'ordre des octets."""
        return BOM + self.line(row)

    def truncation_notice(self, cap: int) -> str:
        """Renvoie la dernière ligne, signalant l'arrêt de l'export au plafond.

        Le fichier arrive par un lien de téléchargement, hors de toute page. Cette ligne est donc le seul avertissement reçu par le lecteur.
        """
        milliers = f"{cap:,}".replace(",", " ")
        return self.line(
            [f"— Export tronqué à {milliers} lignes : affiner les filtres pour l'obtenir entier."]
        )


# Taille visée d'un bloc envoyé au client. Une ligne par bloc ferait des dizaines de milliers d'envois pour un export. Un bloc trop gros reviendrait à tout mettre en tampon.
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


# Plafond de lignes d'un export, avec la requête et le fichier en mémoire. Assez haut pour un export légitime. Assez bas pour qu'une demande sans filtre, répétable par n'importe qui, laisse de la mémoire disponible.
MAX_EXPORT_ROWS = 500_000


def cap_export_rows(
    rows: Sequence[Row[tuple[object, ...]]], cap: int
) -> tuple[Sequence[Row[tuple[object, ...]]], bool]:
    """Renvoie les lignes ramenées au plafond, et si la coupe a eu lieu.

    Les requêtes demandent `cap + 1` lignes : la ligne excédentaire signale le dépassement, sans `COUNT` séparé. La coupe suit le tri appliqué en base.
    """
    if len(rows) <= cap:
        return rows, False
    return rows[:cap], True


def fetch_export_rows(
    conn: Connection, sql: str, binds: dict[str, object], *, name: str
) -> tuple[Sequence[Row[tuple[object, ...]]], bool]:
    """Renvoie les lignes d'un export, ramenées au plafond, et si la coupe a eu lieu.

    Args:
        sql: requête triée, sans clause LIMIT.
        name: nom de l'export dans l'avertissement journalisé lors d'une coupe.
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
    """Renvoie les blocs d'un export CSV : l'en-tête, une ligne par élément de `rows`, puis l'avis de coupe si `truncated`."""

    def lines() -> Iterator[str]:
        writer = CsvWriter()
        yield writer.header(header)
        for row in rows:
            yield writer.line(row)
        if truncated:
            yield writer.truncation_notice(MAX_EXPORT_ROWS)

    return chunked(lines())
