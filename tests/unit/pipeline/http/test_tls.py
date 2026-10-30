"""Contexte TLS des clients HTTP du pipeline."""

import ast
import ssl
from pathlib import Path

from pipeline.http.tls import tls_context

_PIPELINE = Path(__file__).resolve().parents[4] / "pipeline"
# Appels httpx2 qui ouvrent des connexions et créent leur contexte TLS faute de `verify=`.
_CONNECTING = frozenset(
    {"Client", "AsyncClient", "request", "get", "post", "put", "delete", "stream"}
)


def test_le_contexte_verifie_les_certificats_et_est_partage():
    ctx = tls_context()
    assert type(ctx) is ssl.SSLContext
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname
    assert tls_context() is ctx


def test_chaque_appel_httpx2_du_pipeline_recoit_le_contexte():
    """Sans `verify=`, httpx2 crée un contexte truststore, modifié en même temps par des connexions asynchrones simultanées jusqu'au segfault."""
    modules = list(_PIPELINE.rglob("*.py"))
    assert modules
    missing = [
        f"{path.relative_to(_PIPELINE.parent)}:{node.lineno}"
        for path in modules
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "httpx2"
        and node.func.attr in _CONNECTING
        and not any(k.arg == "verify" for k in node.keywords)
    ]
    assert missing == []
