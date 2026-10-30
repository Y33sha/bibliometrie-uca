"""Libellé d'une revue dans le journal du pipeline."""

from pipeline.transformation.publishing.serials.store import SerialSummary


def serial_label(serial: SerialSummary) -> str:
    """Renvoie l'identifiant, le titre, l'éditeur et les ISSN de la revue : `12365 « Livestock Science » (Elsevier BV, 1871-1413/1878-0490)`."""
    issns = "/".join(serial.issns) or "sans ISSN"
    return f"{serial.id} « {serial.title} » ({serial.publisher or 'sans éditeur'}, {issns})"
