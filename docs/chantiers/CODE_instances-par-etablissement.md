# Chantier — Instances par établissement

## Contexte

L'application sert l'Université Clermont Auvergne. Faire tourner la même application pour d'autres universités (Lorraine, Nantes…) permet de juger le pipeline et l'interface sur d'autres corpus. Ces instances servent aux essais locaux et tournent en parallèle de l'instance UCA.

Une grande partie du code est déjà indépendante de l'établissement :

- Le nom de la base vient de `DB_NAME`.
- Les tables `structures` (`hal_collection`, `api_ids`), `perimeters` et `config` désignent l'institution interrogée par chaque source.
- Le verrou du pipeline porte sur une seule base : deux pipelines tournent en même temps sur deux bases.
- Les rôles `bibliometrie_app` et `bibliometrie_pipeline` appartiennent au serveur PostgreSQL. `infrastructure/db/roles.sql` se rejoue base par base.

Obstacles :

1. **Le seed mélange référentiels communs et données propres à UCA.** `infrastructure/db/seed.sql` contient `countries` et `place_name_forms`, mais aussi `structures`, `structure_tutelles`, `perimeters`, `structure_name_forms` et des clés de `config` propres à UCA.
2. **Le frontend suit toujours le `.env` racine.** `svelte.config.js` le charge avec `override: true`, et `vite.config.ts` fait primer son `API_TARGET` sur l'environnement. Un second frontend enverrait ses requêtes au backend UCA.
3. **Le cookie de session est commun à tous les ports d'un même hôte.** Se connecter à une instance servie sur `localhost` déconnecte les autres.
4. **Les ports de l'API (8000) et de vite (5173) sont écrits en dur** dans `start.sh`.
5. **Le nom de l'établissement est écrit en dur** dans les titres de pages, les libellés de facettes (frontend, `infrastructure/read_models/publications/facets.py`, `infrastructure/read_models/stats/summary.py`) et le titre de l'API (`interfaces/api/app.py`). De la logique en dépend aussi :
   - `budget_structure_id === 169` dans `PublicationsListView.svelte` ;
   - `s.code === 'uca'` dans `admin/addresses/+page.svelte` ;
   - les valeurs de repli `"alliance_uca"` dans `infrastructure/sources/config.py` et `"uca"` dans `infrastructure/read_models/perimeters.py`.

## Décisions

- **Une base par établissement** sur le serveur PostgreSQL existant : `bibliometrie_lorraine`, `bibliometrie_nantes`…
- **Seed commun et seed d'établissement.** Le seed commun contient les référentiels partagés par tous les établissements. Le seed d'établissement contient les structures, leurs tutelles, les périmètres, les formes de noms et la configuration propre à l'établissement.
- **Les fichiers des autres établissements sont stockés dans `data/`**, hors versionnement. `data/instances/<nom>/` contient la configuration de l'instance (`instance.env`) et son seed (`seed.sql`).
- **Configuration par surcharge.** `BIBLIO_INSTANCE=<nom>` désigne l'instance. Son `instance.env` se charge après le `.env` racine et contient seulement les valeurs propres à l'instance : `DB_NAME`, les ports, `API_TARGET`. Le backend (`Settings`, `infrastructure/__init__.py`) et le frontend (`svelte.config.js`, `vite.config.ts`) appliquent la même règle. Sans `BIBLIO_INSTANCE`, seul le `.env` racine s'applique.
- **Un nom d'hôte par instance** : `<nom>.localhost`. Les navigateurs le résolvent vers la boucle locale, et chaque instance a son propre cookie de session.
- **Le pipeline des autres établissements tourne sans `--raw-store`.**
- **Une constante porte le nom de l'établissement**, et tous les endroits qui l'affichent la référencent.

## Phasage

### Phase 1 — Seed commun et seed d'établissement

- [ ] `generate_seed` produit deux fichiers : le seed commun (`infrastructure/db/seed.sql`) et le seed d'établissement.
- [ ] Répartir les clés de `config` entre les deux seeds.
- [ ] Mettre à jour l'initialisation de la base dans `docs/exploitation/01-developpement-local.md` et `02-production.md`.

### Phase 2 — Configuration par instance

- [ ] Charger `data/instances/<nom>/instance.env` après `.env` quand `BIBLIO_INSTANCE` est posé, côté backend et côté frontend.
- [ ] Test : une valeur de l'instance prime sur celle du `.env` racine.

### Phase 3 — Création et lancement

- [ ] Script de création d'une instance : création de la base, `alembic upgrade head`, `roles.sql`, seed commun, seed d'établissement.
- [ ] `start.sh <nom>` lance l'API et vite sur les ports de l'instance. Sans argument, il lance l'instance UCA sur 8000 et 5173.
- [ ] Documenter le lancement du pipeline et des scripts sur une instance (`BIBLIO_INSTANCE=<nom> run_pipeline …`).

### Phase 4 — Nom de l'établissement

- [ ] Constante du nom, référencée par les titres, les libellés du frontend et du backend, et le titre de l'API.
- [ ] Remplacer la logique qui dépend de l'identifiant 169 et des codes `uca` et `alliance_uca`.

### Phase 5 — Seeds d'autres établissements

- [ ] Générer le seed d'un établissement à partir de ROR (structures filles), du référentiel des structures HAL et des identifiants d'institution OpenAlex. Les formes de noms de départ viennent des noms et des acronymes.
- [ ] Seeds Université de Lorraine et Nantes Université dans `data/instances/`.
- [ ] Faire tourner le pipeline sur chaque instance et examiner le résultat dans l'interface.

## Questions ouvertes

- **Seed d'établissement UCA.** La production s'initialise depuis `infrastructure/db/seed.sql`. Le seed UCA reste-t-il versionné, ou rejoint-il `data/` comme les autres ?
- **Valeur du nom par instance.** Une constante de code a la même valeur dans toutes les instances. Pour Lorraine ou Nantes, sa valeur vient-elle de `instance.env` ou de la table `config` du seed d'établissement ?
- **Valeurs de filtre `uca`, `non_uca`, `other_uca`.** L'API les expose, et elles reposent sur `perimeter_persons`. Faut-il les renommer avec la phase 4 ?
- **Journaux sur disque.** Avec `LOG_TO_FILE=true`, toutes les instances écrivent sous le même `logs/`.
