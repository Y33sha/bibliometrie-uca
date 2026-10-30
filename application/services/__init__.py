"""Services applicatifs, un module par entité du domaine ou par traitement.

Un service applique la règle métier d'une écriture. La transaction appartient à l'appelant, qui commite. Pour l'API, c'est la requête (`db_conn`, dans `interfaces/api/deps.py`), commitée au succès avant l'envoi de la réponse. Le pipeline et les scripts commitent eux-mêmes.
"""
