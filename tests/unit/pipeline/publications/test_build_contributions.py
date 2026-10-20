"""Construction de la table `contributions` : les stats de `source_contributions` sont fraîches avant chaque requête qui filtre sur une colonne réécrite en masse."""


class _QueriesEnregistrees:
    """Enregistre le nom de chaque requête appelée et rend zéro."""

    def __init__(self) -> None:
        self.appels: list[str] = []

    def __getattr__(self, nom: str):
        def requete(conn, *args, **kwargs) -> int:
            self.appels.append(nom)
            return 0

        return requete
