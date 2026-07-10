"""Services applicatifs autour de la table `config` (paramètres clé / valeur JSON).

Sous-modules :
- ``core`` : briques transaction-agnostiques (mise à jour de valeur), réutilisées
  par l'API et les CLI.
- ``commands`` : command handlers de l'API (frontière transactionnelle, commit).
"""
