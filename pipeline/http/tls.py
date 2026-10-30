"""Contexte TLS des clients HTTP du pipeline."""

import ssl
from functools import cache


@cache
def tls_context() -> ssl.SSLContext:
    """Renvoie le contexte TLS standard, partagé par tous les clients httpx2 du pipeline (`verify=`).

    Il vérifie les certificats avec les certificats racine du système (`SSL_CERT_FILE`, `SSL_CERT_DIR`, sinon les chemins par défaut d'OpenSSL). Il reste inchangé après sa création, donc des connexions simultanées le partagent sans risque.
    """
    return ssl.create_default_context()
