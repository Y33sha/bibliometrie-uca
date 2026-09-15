"""Construction de la table `authorships` : les stats de `source_authorships` sont fraîches avant chaque requête qui filtre sur une colonne réécrite en masse."""

import logging

from application.pipeline.authorships.build_authorships import build


class _QueriesEnregistrees:
    """Enregistre le nom de chaque requête appelée et rend zéro."""

    def __init__(self) -> None:
        self.appels: list[str] = []

    def __getattr__(self, nom: str):
        def requete(conn, *args, **kwargs) -> int:
            self.appels.append(nom)
            return 0

        return requete


def test_stats_de_source_authorships_fraiches_avant_la_creation_des_liens():
    """Les phases normalize et persons réécrivent `person_id` juste avant : l'insertion des liens filtre sur cette colonne."""
    queries = _QueriesEnregistrees()

    build(object(), queries, logging.getLogger("test"))

    assert queries.appels.index("analyze_source_authorships") < queries.appels.index(
        "insert_missing_authorships"
    )


def test_stats_de_source_authorships_fraiches_avant_la_propagation_des_attributs():
    """La liaison vient de poser `authorship_id`, sur lequel la propagation filtre."""
    queries = _QueriesEnregistrees()

    build(object(), queries, logging.getLogger("test"))

    liaison = queries.appels.index("link_source_authorships_to_authorships")
    propagation = queries.appels.index("propagate_authorship_attributes")
    assert "analyze_source_authorships" in queries.appels[liaison:propagation]
