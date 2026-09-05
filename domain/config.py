"""Règles de confidentialité des paramètres applicatifs.

La table `config` porte les réglages d'exploitation du pipeline : périmètres, années couvertes, types de structure affichés. Une part est consommée par les pages publiques, le reste est réservé à une session d'administration.
"""

# Clés de configuration consommées par une page publique
PUBLIC_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        # Types de structure affichés par la page des laboratoires.
        "laboratories_display_types",
    }
)
