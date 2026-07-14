"""Services applicatifs, un package par agrégat du domaine.

Deux rôles, portés par des modules distincts :

- **Briques d'écriture** transaction-agnostiques (le plus souvent `core.py`, parfois éclatées comme `addresses/structures.py` et `addresses/countries.py`) : elles appliquent la règle métier sans committer. Certaines sont réutilisées par le pipeline, les CLI et l'API ; d'autres ne servent que l'API mais restent séparées pour isoler la logique métier de la frontière transactionnelle.
- **Command handlers** (`commands.py`), quand l'API écrit sur l'agrégat : une écriture API est une commande (intention courte d'un acteur). Le handler reçoit la connexion de la requête, compose les briques agnostiques et `conn.commit()` au succès, pour que la donnée soit persistée avant l'envoi de la réponse ; seul le handler commit.

Une écriture API triviale peut tenir directement dans `commands.py`, sans brique séparée (`config`).
"""
