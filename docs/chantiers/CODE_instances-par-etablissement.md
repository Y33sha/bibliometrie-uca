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
- **Seed commun et seed d'établissement.** Le seed commun contient les référentiels partagés par tous les établissements. Le seed d'établissement contient les structures, leurs tutelles, les périmètres, les formes de noms et la configuration propre à l'établissement. Le seed d'établissement UCA reste versionné et sert d'exemple.
- **Les fichiers des autres établissements sont stockés dans `instances/`**, à la racine, hors versionnement. `instances/<nom>/` contient la configuration de l'instance (`instance.env`) et son seed d'établissement (`seed.sql`).
- **Configuration par surcharge.** La variable d'environnement `BIBLIO_INSTANCE=<nom>` désigne l'instance. `instances/<nom>/instance.env` contient seulement les valeurs propres à l'instance : `DB_NAME`, les ports, `API_TARGET`. Le backend (`infrastructure/__init__.py`) et le frontend (`project-env.js`) appliquent la même règle :
  - sans `BIBLIO_INSTANCE`, seul le `.env` racine s'applique ;
  - avec `BIBLIO_INSTANCE`, les valeurs de l'instance priment sur l'environnement du processus et sur le `.env` racine. Un terminal VSCode injecte le `.env` racine dans l'environnement, d'où la priorité sur l'environnement du processus ;
  - si le fichier de l'instance manque, le démarrage échoue en nommant le chemin attendu.
- **Un nom d'hôte par instance** : `<nom>.localhost`. Les navigateurs le résolvent vers la boucle locale, et chaque instance a son propre cookie de session.
- **Le pipeline des autres établissements tourne sans `--raw-store`, avec `LOG_TO_FILE=false`.**
- **Le nom de l'établissement est le nom du périmètre `perimeter_persons`** (`perimeters.name`). Le seed d'établissement le fournit, et la lecture publique de la configuration le sert au frontend.

## Phasage

### Phase 1 — Seed commun et seed d'établissement

- [x] `generate_seed` produit deux fichiers : le seed commun (`infrastructure/db/seed.sql`) et le seed d'établissement UCA.
- [x] Répartir les clés de `config` entre les deux seeds.
- [x] Mettre à jour l'initialisation de la base dans `docs/exploitation/01-developpement-local.md` et `02-production.md`.

### Phase 2 — Configuration par instance

- [x] Ajouter `instances/` au `.gitignore`.
- [x] Charger `instances/<nom>/instance.env` après `.env` quand `BIBLIO_INSTANCE` est posé, côté backend et côté frontend.
- [x] Test : une valeur de l'instance prime sur celle du `.env` racine.

### Phase 3 — Création et lancement

- [ ] Script de création d'une instance : création de la base, `alembic upgrade head`, `roles.sql`, seed commun, seed d'établissement.
- [ ] `start.sh <nom>` lance l'API et vite sur les ports de l'instance. Sans argument, il lance l'instance UCA sur 8000 et 5173.
- [ ] Documenter le lancement du pipeline et des scripts sur une instance (`BIBLIO_INSTANCE=<nom> run_pipeline …`).

### Phase 4 — Nom de l'établissement

- [ ] Servir le nom du périmètre `perimeter_persons` au frontend par la lecture publique de la configuration.
- [ ] Référencer ce nom dans les titres, les libellés du frontend et du backend, et le titre de l'API.
- [ ] Remplacer la logique qui dépend de l'identifiant 169 et des codes `uca` et `alliance_uca`.

### Phase 5 — Seeds d'autres établissements

- [ ] Générer le seed d'un établissement à partir de ROR (structures filles), du référentiel des structures HAL et des identifiants d'institution OpenAlex. Les formes de noms de départ viennent des noms et des acronymes.
- [ ] Seeds Université de Lorraine et Nantes Université dans `instances/`.
- [ ] Faire tourner le pipeline sur chaque instance et examiner le résultat dans l'interface.

### Phase 6 — Valeurs de filtre

- [ ] Renommer les valeurs de filtre `uca`, `non_uca` et `other_uca` exposées par l'API.
