"""Règles de confidentialité des paramètres applicatifs.

La table `config` porte les réglages d'exploitation du pipeline : périmètres, années couvertes, types de structure affichés. Une part est consommée par les pages publiques, le reste est réservé à une session d'administration.

Les identifiants d'accès aux sources n'y figurent pas : ce sont des secrets, lus depuis l'environnement du processus comme les autres secrets de l'application (cf. `infrastructure.settings`).
"""

# Clés que la lecture publique de la configuration rend. Liste blanche : une clé qu'on n'y
# inscrit pas reste réservée à une session, ce qui protège par défaut tout réglage ajouté
# sans que quiconque ait tranché sa nature. Une clé y figure quand une page publique la
# consomme, et pour cette raison seule.
PUBLIC_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        # Types de structure affichés par la page des laboratoires.
        "laboratories_display_types",
    }
)
