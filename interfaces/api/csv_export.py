"""Réponse de téléchargement d'un export CSV, envoyée par blocs."""

from collections.abc import Iterator

from fastapi.responses import StreamingResponse

from interfaces.api.rate_limit import ExportSlot, releasing


def csv_response(chunks: Iterator[str], *, filename: str, slot: ExportSlot) -> StreamingResponse:
    """Emballe les blocs d'un export en réponse de téléchargement, envoyés au fil de leur production.

    La mémoire tenue pendant l'envoi vaut un bloc à la fois, plus les lignes que la requête a ramenées.

    Le droit d'export passe au flux, qui le rend quand le parcours s'achève : la mémoire reste prise tant que le corps part, et le cycle de vie des dépendances s'achève avant.

    Le statut et les en-têtes partent avec le premier bloc : une erreur survenant pendant l'envoi ferme la connexion sur un fichier tronqué, sous un statut 200. Les lignes sont en mémoire à ce stade, la requête s'étant exécutée avant que la réponse ne commence.
    """
    return StreamingResponse(
        releasing(chunks, slot),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
