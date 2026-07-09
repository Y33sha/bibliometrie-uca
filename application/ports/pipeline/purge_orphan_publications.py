"""Port : purge des publications orphelines + reclaim de l'espace (fin de phase authorships).

Implémenté par `infrastructure.queries.pipeline.purge_orphan_publications.PgPurgeOrphanPublicationsQueries`.
"""

from typing import Protocol

from sqlalchemy import Connection


class PurgeOrphanPublicationsQueries(Protocol):
    """Suppression des publications sans authorship et récupération de l'espace churné."""

    def purge_orphan_publications(self, conn: Connection, *, limit: int | None = None) -> int:
        """Supprime les publications sans aucun authorship (un chunk si `limit`).

        Retourne le nombre supprimé. Le batching (boucle + commit par chunk) est piloté par
        l'orchestrateur de phase.
        """
        ...

    def vacuum_analyze_churned(self) -> None:
        """Récupère l'espace des tuples morts churnés par la purge (maintenance physique).

        Opère hors transaction : l'adapter ouvre sa propre connexion autocommit — le `VACUUM`
        ne lit ni n'écrit de donnée métier et ne peut rejoindre une transaction, il sort donc
        du périmètre des transactions injectées.
        """
        ...
