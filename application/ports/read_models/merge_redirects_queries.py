"""Port : redirection de l'identifiant d'une entité absorbée par une fusion.

Implémenté par `infrastructure.read_models.merge_redirects.PgMergeRedirectQueries`.
"""

from typing import Protocol

from domain.merge import MergedEntity


class MergeRedirectQueries(Protocol):
    def kept_id(self, entity: MergedEntity, absorbed_id: int) -> int | None:
        """Identifiant de l'entité conservée vers laquelle mène `absorbed_id`, ou `None` sans redirection."""
        ...
