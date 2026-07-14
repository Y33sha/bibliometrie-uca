"""Services applicatifs autour de l'agrégat Authorship.

Sous-modules :
- `core` : briques transaction-agnostiques (exclusion d'une contribution, rejet de paire, propagation d'`in_perimeter`), réutilisées par l'API et le service des personnes.
- `assign_orphans` : rattachement d'authorships orphelines à une personne (unitaire et par lot).
- `commands` : command handlers de l'API (frontière transactionnelle, commit).
"""
