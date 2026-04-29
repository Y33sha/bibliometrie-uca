# Chantier — DRY publications tables

## Contexte

Le tableau de publications avec ses filtres facets (années, labos, types,
accès, OA, APC, pays, sources) et son tri (titre, année, APC) est répété à
plusieurs endroits du frontend :

- `interfaces/frontend/src/routes/publications/+page.svelte` — page autonome
  (~440 lignes avant refacto Phase 5e du chantier sujets/mots-clés).
- `interfaces/frontend/src/routes/laboratories/[id]/+page.svelte` — onglet
  "Publications" parmi d'autres onglets (~1170 lignes au total).
- `interfaces/frontend/src/routes/persons/[id]/+page.svelte` — onglet
  "Publications" parmi d'autres onglets (~750 lignes au total).

Chaque implémentation re-déclare le markup des colonnes, les composables
de pagination/facets/colonnes, les handlers de tri, etc., avec quelques
variations mineures (filtres pré-positionnés, libellés, colonnes par défaut).

## Travail déjà fait (Phase 5e du chantier sujets/mots-clés)

Lors de l'ajout de l'onglet "Publications" sur `/subjects/[id]`, on a
extrait `<PublicationsListView>` dans
`interfaces/frontend/src/lib/components/PublicationsListView.svelte`,
réutilisé par :

- `/publications` (mode autonome avec sync URL).
- `/subjects/[id]?tab=publications` (filtre `subject_id` fixe imposé par
  la route, pas de sync URL, pas de banner).

Le composant accepte les props :

- `apiKey: string` — clé pour le cache de `usePaginatedFetch`/`useFacets`.
- `externalFilters?: { subjectId?, subjectLabel? }` — filtres fixes du
  contexte parent, ajoutés au backend via `subject_id` (paramètre déjà
  présent dans `/api/publications`).
- `urlSync?: boolean` — true pour `/publications`, false sinon.
- `basePath?: string` — utilisé par `useUrlFilters` et `cleanFilterUrl`.
- `showFilterBanner?: boolean` — banner publisher/journal/subject avec
  lien "Supprimer le filtre".

`/publications/+page.svelte` est devenue un wrapper léger.

## Reste à faire

Migrer `/laboratories/[id]` et `/persons/[id]` vers `<PublicationsListView>`
pour leur onglet "Publications" respectif.

### Variations à supporter (à confirmer par lecture du code)

- Filtres pré-positionnés (lab_id pour `/laboratories/[id]`, person_id pour
  `/persons/[id]`) : à passer via `externalFilters` enrichi (ajouter
  `labId`, `personId` au type) ou via un mécanisme dédié.
- Colonnes par défaut différentes (ex la colonne "Labo(s)" est probablement
  cachée par défaut sur `/laboratories/[id]` puisque le labo est connu).
- Boutons d'export CSV éventuellement spécifiques (`export.csv` vs
  `export-theses.csv`).
- Liens vers la page (sync URL avec `?tab=` au lieu de query params bruts).

### Risques

`/laboratories/[id]` et `/persons/[id]` sont des pages très utilisées par
le client (Laura). Toute régression sur l'onglet Publications est
particulièrement gênante. À tester soigneusement après migration :

- Filtres facets fonctionnent (toutes les combinaisons).
- Pagination, tri, recherche.
- Filtres pré-positionnés (lab_id / person_id) appliqués correctement.
- Liens vers les détails publication, retour fonctionnel.
- Export CSV si applicable.
- Persistence URL avec les autres onglets de la page (`?tab=publications`
  vs autres onglets `dashboard`, `theses`, `addresses`, etc.).

### Étapes proposées

1. Lire `/laboratories/[id]` et `/persons/[id]` pour identifier les écarts
   précis avec `PublicationsListView`.
2. Étendre les props du composant si nécessaire (ex `labId`, `personId`,
   colonnes initiales custom).
3. Migrer une page à la fois, en validant exhaustivement chaque cas avant
   de passer à la suivante.
4. Garder un `git diff` lisible (commits séparés par page).

## À faire après cleanup éventuel

Si la migration révèle qu'aucune variation utile ne nécessite plus de
filtres externes hors `subject_id`/`publisher_id`/`journal_id`/`labId`/
`personId`, on peut envisager de simplifier `ExternalFilters` en un type
plus contraint (union discriminée plutôt que tous les champs optionnels).
