# Chantier — Jeu de données commun aux tests du pipeline

## Contexte

Les tests d'idempotence préparent leurs données phase par phase : chacun fabrique à la main les tables que sa phase lit (notices, signatures, publications). Ces données peuvent différer de ce que les phases précédentes produisent réellement, sans que rien le signale.

Aucun test n'enchaîne toutes les phases. Le graphe de dépendances (`pipeline/graph.py`) déclare ce que chaque nœud lit et écrit ; rien ne vérifie ces déclarations contre le code, faute d'un banc où exécuter chaque nœud sur des données réalistes.

## Décisions

- **Un jeu de notices réelles, quelques-unes par source**, déposé dans `staging` comme le ferait l'extraction. Les notices couvrent les cas que le pipeline traite : DOI partagé entre sources, thèse, actes, liste d'auteurs tronquée, homonymes, ISSN multiples.
- **Les appels réseau sont simulés** par des réponses enregistrées, une par API.
- **Le jeu sert trois tests** :
  - un run complet de bout en bout ;
  - l'idempotence du run entier : un second run ne change rien ;
  - la fidélité du graphe : les tables réellement lues et écrites par chaque nœud, mesurées par les compteurs de PostgreSQL (`pg_stat_xact_user_tables`), sont incluses dans ses déclarations.

## Phasage

### Phase 1 — Le jeu

- [ ] Choisir les notices et les cas qu'elles couvrent.
- [ ] Les figer dans le dépôt, avec les réponses des API.
- [ ] Un module de test qui charge le jeu dans `staging`.

### Phase 2 — Run complet

- [ ] Enchaîner toutes les phases sur le jeu, appels réseau simulés.
- [ ] Vérifier le résultat sur quelques entités choisies.
- [ ] Vérifier qu'un second run ne change rien.

### Phase 3 — Fidélité du graphe

- [ ] Mesurer les tables lues et écrites par chaque nœud ; écarter les contrôles de clés étrangères, qui parcourent les tables enfants d'une suppression.
- [ ] Échouer sur toute table touchée et non déclarée.

### Phase 4 — Tests d'idempotence existants

- [ ] Les faire reposer sur le jeu commun, ou les retirer s'il les couvre.

## Questions ouvertes

- Taille du jeu : assez de notices pour couvrir les cas, assez peu pour un run de test en quelques secondes ?
- Les réponses enregistrées vieillissent avec les API : comment les rafraîchir ?
