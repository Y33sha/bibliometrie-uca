"""Réponse d'une route de détail à un identifiant sans entité : redirection 308 vers l'entité conservée par une fusion, sinon 404."""

from dataclasses import dataclass

from fastapi import HTTPException, Request

from domain.merge import MergedEntity
from infrastructure.read_models.merge_redirects import MergeRedirectQueries

_NOT_FOUND = {
    MergedEntity.PERSON: "Personne introuvable",
    MergedEntity.SERIAL: "Revue introuvable",
    MergedEntity.PUBLISHER: "Éditeur introuvable",
    MergedEntity.MONOGRAPH: "Monographie introuvable",
    MergedEntity.PUBLICATION: "Publication introuvable",
}


@dataclass(frozen=True, slots=True)
class EntityDetail:
    """Détail d'une entité, pour une route dont le seul paramètre de chemin est l'identifiant de l'entité."""

    entity: MergedEntity
    request: Request
    redirects: MergeRedirectQueries

    def found[T](self, detail: T | None) -> T:
        """Retourne `detail`. Sans détail, lève une redirection 308 vers l'identifiant conservé, ou un 404 sans redirection.

        La redirection garde la route et la query string de la requête, et seul l'identifiant change. Son `Location` est relatif : il passe par le même hôte que la requête.
        """
        if detail is not None:
            return detail
        ((param, raw_id),) = self.request.path_params.items()
        kept_id = self.redirects.kept_id(self.entity, int(raw_id))
        if kept_id is None:
            raise HTTPException(status_code=404, detail=_NOT_FOUND[self.entity])
        route_name = self.request.scope["route"].name
        location = self.request.url_for(route_name, **{param: str(kept_id)}).path
        if self.request.url.query:
            location += f"?{self.request.url.query}"
        raise HTTPException(status_code=308, headers={"Location": location})
