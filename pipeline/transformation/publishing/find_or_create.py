"""Recherche et création de l'éditeur d'un enregistrement source.

Les normaliseurs des sources appellent ces fonctions pour chaque enregistrement source. La revue et la monographie se rattachent dans la phase `publishing` (`attach_serials`, `attach_monographs`).
"""

from domain.normalize import normalize_text
from domain.publishers.names import publisher_name_key
from pipeline.transformation.publishing.publishers.store import PublisherStore


def find_or_create_publisher(
    name: str | None,
    *,
    openalex_id: str | None = None,
    repo: PublisherStore,
) -> int | None:
    """Trouve ou crée un éditeur. Renvoie son id, ou `None` si le nom est vide.

    Recherche par `openalex_id`, puis par la clé de nom (`publisher_name_key`) parmi les formes de nom. Sans correspondance, l'éditeur est créé avec sa forme de nom.
    """
    if not name:
        return None

    # 1. Par openalex_id
    if openalex_id:
        publisher_id = repo.find_publisher_by_openalex_id(openalex_id)
        if publisher_id:
            name_key = publisher_name_key(name)
            if name_key:
                repo.add_publisher_name_form(publisher_id, name_key)
            return publisher_id

    # 2-3. Par forme de nom, ou création, puis attribution de l'`openalex_id` à l'éditeur trouvé ou créé.
    matched = match_or_create_publisher(name, repo=repo)
    if matched is None:
        return None
    publisher_id, _ = matched
    if openalex_id:
        repo.set_publisher_openalex_id_if_missing(publisher_id, openalex_id)
    return publisher_id


def match_or_create_publisher(name: str, *, repo: PublisherStore) -> tuple[int, bool] | None:
    """Trouve par sa clé de nom, ou crée, l'éditeur désigné par `name`. Renvoie `(id, created)`, ou `None` si le nom est vide une fois normalisé."""
    name_normalized = normalize_text(name)
    name_key = publisher_name_key(name)
    if not name_normalized or not name_key:
        return None
    return repo.match_or_create_by_name_form(name, name_normalized, name_key)
