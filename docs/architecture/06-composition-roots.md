# Composition roots

*À jour le 2026-10-26.*

Un composition root est l'endroit où les adaptateurs concrets sont instanciés et câblés aux services et orchestrateurs. Ailleurs, on reçoit un port en paramètre.

**L'API en a deux.**
- `app.py` construit l'engine au démarrage et le libère à l'arrêt ;
- `deps.py` contient les fabriques qui construisent les read models et les services d'écriture sur la connexion de la requête, et que les routes reçoivent par `Depends`.

**Chaque programme en ligne de commande est son propre composition root.**
- Dans `run_pipeline`, la fonction `build()` de chaque phase instancie ses requêtes et ses clients.
- Les scripts CLI font de même, sans la séparation entre construction et appel que l'API impose. Un script qui appelle un service d'écriture le construit par la fabrique de `deps.py`, sur sa propre connexion.
