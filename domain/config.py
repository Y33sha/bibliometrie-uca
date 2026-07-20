"""Règles de confidentialité des paramètres applicatifs.

La table `config` porte deux natures de réglages : des paramètres d'exploitation que les pages publiques consomment, et les identifiants d'accès aux sources — clés d'API, comptes de service, adresse du polite pool.
"""

# Clés que la lecture publique de la configuration rend. Liste blanche : une clé qu'on n'y
# inscrit pas reste réservée à une session, ce qui protège par défaut tout réglage ajouté
# sans que quiconque ait tranché sa nature.
PUBLIC_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "laboratories_display_types",
        "perimeter_extraction",
        "perimeter_persons",
        "pipeline_start_year_full",
    }
)
