"""Périmètre d'extraction : condition d'exécution des phases qui en dépendent."""


class EmptyExtractionPerimeterError(RuntimeError):
    """Le périmètre d'extraction ne contient aucune structure. Les phases qui en dépendent s'arrêtent en échec."""

    def __init__(self) -> None:
        super().__init__(
            "Le périmètre d'extraction est vide : la clé `perimeter_extraction` est absente de "
            "`config`, ou désigne un périmètre sans structure."
        )
