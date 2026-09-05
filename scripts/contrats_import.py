"""Types de contrat maison pour `import-linter`.

Déclarés dans `pyproject.toml`, section `[tool.importlinter]`, clé `contract_types`.
"""

import sys

from grimp import ImportGraph
from importlinter import Contract, ContractCheck, fields, output


class PureteDuNoyau(Contract):
    """Un paquet n'importe que la bibliothèque standard, lui-même, et ce que `autorises` énumère.

    Là où un contrat `forbidden` énumère l'interdit, celui-ci énumère le permis : un paquet tiers
    ajouté aux dépendances du projet est signalé sans qu'on ait eu à le prévoir.

    Options :
        - paquet : le paquet dont les imports sont contrôlés.
        - autorises : noms de premier niveau admis en plus de la bibliothèque standard (facultatif).
    """

    type_name = "purete_du_noyau"

    # À l'exécution, ces attributs portent les valeurs lues dans la configuration.
    paquet: str = fields.StringField()  # type: ignore[assignment]
    autorises: list[str] | None = fields.ListField(  # type: ignore[assignment]
        subfield=fields.StringField(), required=False
    )

    def check(self, graph: ImportGraph, verbose: bool) -> ContractCheck:
        permis = set(sys.stdlib_module_names) | {self.paquet} | set(self.autorises or [])
        infractions = [
            (module, importe)
            for module in sorted({self.paquet} | graph.find_descendants(self.paquet))
            for importe in sorted(graph.find_modules_directly_imported_by(module))
            if importe.split(".")[0] not in permis
        ]
        return ContractCheck(kept=not infractions, metadata={"infractions": infractions})

    def render_broken_contract(self, check: ContractCheck) -> None:
        for module, importe in check.metadata["infractions"]:
            output.print_error(f"{module} importe {importe}")
