# Composition roots

*À jour le 2026-09-05.*

Un composition root est l'endroit où les adaptateurs concrets sont instanciés et câblés aux services et orchestrateurs. Ailleurs, on reçoit un port en paramètre.

**L'API en a deux.**
- `app.py` construit l'engine au démarrage et le libère à l'arrêt ;
- `deps.py` contient les fabriques qui câblent repositories, read models et query services sur la connexion de la requête, et que les routes reçoivent par `Depends`.

**Chaque programme en ligne de commande est son propre composition root.**
- Dans `run_pipeline`, la fonction `build()` de chaque phase instancie ses requêtes et ses clients.
- Tous les scripts CLI font de même, sans la séparation entre construction et appel que l'API impose.
