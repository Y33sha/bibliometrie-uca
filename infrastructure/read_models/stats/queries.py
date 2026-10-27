"""Lecture des agrégats des tableaux de bord (router stats).

Le package est organisé par thème d'agrégat, une classe par module :
- `pivot` : agrégation générique et schéma de son registre
- `collaborations` : décompte des pays étrangers co-affiliés

Leurs conditions de filtrage sont celles de la liste des publications (`publications.filtering`). Les décomptes des filtres sont ceux de la liste.

`StatsQueries` réunit ces classes.
"""

from sqlalchemy import Connection

from infrastructure.read_models.stats.collaborations import StatsCollaborationQueries
from infrastructure.read_models.stats.pivot import StatsPivotQueries


class StatsQueries(StatsPivotQueries, StatsCollaborationQueries):
    """Agrégats des tableaux de bord.

    Le filtre `has_apc` classe un paiement d'APC en « interne » quand sa structure de budget appartient au périmètre `persons`. La lecture résout ce périmètre là où il sert : ses appelants n'ont pas à le connaître pour demander des statistiques.
    """

    def __init__(self, conn: Connection) -> None:
        self._conn = conn


__all__ = ["StatsQueries"]
