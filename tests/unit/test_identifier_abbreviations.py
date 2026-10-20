"""Les identifiants Python écrivent les noms d'entité en entier.

Un identifiant se découpe en segments, en snake_case comme en CamelCase. Les segments `pub` (publication), `sp` et `sd` (enregistrement source) et `nf` (forme de nom) sont refusés, au singulier comme au pluriel. `sa` reste l'alias usuel de SQLAlchemy. Les alias de table du SQL, dans les chaînes, échappent au test.
"""

import ast
import re

from infrastructure import PROJECT_ROOT

ABBREVIATIONS = {"pub", "pubs", "sp", "sps", "sd", "sds", "nf", "nfs"}
PACKAGES = ("application", "domain", "infrastructure", "interfaces", "pipeline", "tests")


def _names(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.arg):
            yield node.lineno, node.arg
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.lineno, node.name


def _segments(name: str) -> set[str]:
    return set(re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower().split("_"))


def test_aucun_identifiant_n_abrege_un_nom_d_entite() -> None:
    offenders = [
        f"{path.relative_to(PROJECT_ROOT)}:{line} {name}"
        for package in PACKAGES
        for path in sorted((PROJECT_ROOT / package).rglob("*.py"))
        if "node_modules" not in path.parts
        for line, name in _names(ast.parse(path.read_text(encoding="utf-8")))
        if _segments(name) & ABBREVIATIONS
    ]
    assert offenders == []
