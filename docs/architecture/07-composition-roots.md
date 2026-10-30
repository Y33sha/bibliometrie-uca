# Composition roots

*À jour le 2026-10-26.*

Un composition root instancie les adaptateurs concrets et les remet aux services. Le reste du code reçoit ses dépendances en paramètre.

**L'API en a deux.**
- `app.py` construit l'engine au démarrage et le libère à l'arrêt ;
- `deps.py` contient les fabriques des read models et des services d'écriture, construits sur la connexion de la requête et reçus par les routes via `Depends`.

**Chaque programme en ligne de commande est son propre composition root.**
- Dans `run_pipeline`, la fonction `build()` de chaque phase instancie ses requêtes et ses clients.
- Les scripts CLI font de même, sans la séparation entre construction et appel imposée par l'API. Un script qui appelle un service d'écriture le construit par la fabrique de `deps.py`, sur sa propre connexion.
