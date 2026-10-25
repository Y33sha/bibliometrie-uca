"""Services applicatifs, un package par agrégat du domaine.

Un service applique la règle métier d'une écriture et ne committe pas : la transaction appartient à l'appelant. Pour l'API, c'est la requête (`db_conn`, dans `interfaces/api/deps.py`), committée au succès avant l'envoi de la réponse. Le pipeline et les scripts committent eux-mêmes.
"""
