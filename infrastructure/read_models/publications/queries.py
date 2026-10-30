"""Lectures des publications, pour les routes `/api/publications`.

Le package est organisé par thème, une classe par module :
- `list` : liste paginée, exports CSV des publications et des thèses
- `facets` : facettes de la liste, facette d'entité
- `detail` : détail d'une publication
- `source_records` : enregistrements sources et contributions sources d'une publication
- `suspect_merges` : file des fusions suspectes
- `merge_candidates` : candidats à la fusion manuelle avec une publication

`PublicationsQueries` réunit ces classes.
"""

from collections.abc import Callable

from sqlalchemy import Connection

from infrastructure.read_models.publications.detail import PublicationDetailQueries
from infrastructure.read_models.publications.facets import PublicationFacetQueries
from infrastructure.read_models.publications.list import PublicationListQueries
from infrastructure.read_models.publications.merge_candidates import MergeCandidateQueries
from infrastructure.read_models.publications.source_records import PublicationSourceRecordQueries
from infrastructure.read_models.publications.suspect_merges import SuspectMergeQueries


class PublicationsQueries(
    PublicationListQueries,
    PublicationFacetQueries,
    PublicationDetailQueries,
    PublicationSourceRecordQueries,
    SuspectMergeQueries,
    MergeCandidateQueries,
):
    """Lectures sur les publications.

    Le filtre `has_apc` classe un paiement d'APC en « interne » quand sa structure de budget appartient au périmètre des personnes. Ce périmètre est résolu par la lecture, sans intervention des appelants.
    """

    def __init__(self, conn: Connection, *, open_connection: Callable[[], Connection]) -> None:
        """Reçoit la connexion de la requête et l'ouverture des connexions supplémentaires.

        Args:
            open_connection: ouvre les connexions du calcul parallèle des facettes. La composition root la fournit, avec les caractéristiques de la requête en cours.
        """
        self._conn = conn
        self._open_connection = open_connection


__all__ = ["PublicationsQueries"]
