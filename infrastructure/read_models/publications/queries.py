"""Lecture des publications (router publications).

Le package est organisé par thème, une classe par module :
- `list` : liste paginée, exports CSV des publications et des thèses
- `facets` : facettes de la liste, facette d'entité
- `detail` : détail d'une publication
- `source_records` : enregistrements sources et contributions sources d'une publication
- `suspect_merges` : file des fusions suspectes

`PublicationsQueries` réunit ces classes.
"""

from collections.abc import Callable

from sqlalchemy import Connection

from infrastructure.read_models.publications.detail import PublicationDetailQueries
from infrastructure.read_models.publications.facets import PublicationFacetQueries
from infrastructure.read_models.publications.list import PublicationListQueries
from infrastructure.read_models.publications.source_records import PublicationSourceRecordQueries
from infrastructure.read_models.publications.suspect_merges import SuspectMergeQueries


class PublicationsQueries(
    PublicationListQueries,
    PublicationFacetQueries,
    PublicationDetailQueries,
    PublicationSourceRecordQueries,
    SuspectMergeQueries,
):
    """Lectures sur les publications.

    Le filtre `has_apc` classe un paiement d'APC en « interne » quand sa structure de budget appartient au périmètre `persons`. La lecture résout ce périmètre là où il sert : ses appelants n'ont pas à le connaître pour lister des publications.
    """

    def __init__(self, conn: Connection, *, open_connection: Callable[[], Connection]) -> None:
        """`open_connection` ouvre les connexions supplémentaires dont le calcul parallèle des facettes se sert. Elle est fournie par la composition root, qui y met les caractéristiques de la requête en cours ; l'adapter reçoit ses connexions, il n'en ouvre pas de son propre chef."""
        self._conn = conn
        self._open_connection = open_connection


__all__ = ["PublicationsQueries"]
