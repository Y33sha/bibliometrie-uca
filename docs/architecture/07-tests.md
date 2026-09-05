# Tests

*À jour le 2026-09-05.*

## Deux suites Python

- **Unitaires** (`tests/unit/`) — sans base. Couvrent `domain/`, les services de `application/` sur mocks, la lecture des formats sources, l'infrastructure sans entrée-sortie, et les interfaces.
- **Intégration** (`tests/integration/`) — sur une base `bibliometrie_test`, recréée par `alembic upgrade head` au début de la session. Chaque test travaille dans une transaction annulée à sa sortie. Couvrent les routers, les orchestrateurs de phase, les adaptateurs, et le démarrage des programmes en ligne de commande.

Les tests d'intégration se connectent sous les mêmes rôles que les processus en production, et les droits accordés à la base de test sont extraits de `infrastructure/db/roles.sql` plutôt que recopiés. Une écriture hors des droits d'un rôle échoue donc ici, nommément, au lieu d'aboutir et de casser une fois déployée.

## Le frontend

`npm test` lance vitest sur `interfaces/frontend/`. L'intégration continue y ajoute le contrôle de types (`npm run check`, qui échoue sur toute erreur) et eslint.

## Couverture

Le seuil global est `fail_under = 90`, sur une mesure qui compte les branches et pas seulement les lignes (`branch = true`). Une liste courte de modules — ceux qui décident d'un accès, bornent une entrée, ferment une connexion à l'écriture ou tracent une action d'administration — est tenue à `fail_under = 100`.

Sont hors du calcul les scripts à usage unique et le dialogue HTTP des adaptateurs sources — pagination, attente, appels — dont la logique utile vit dans des modules mesurés.
