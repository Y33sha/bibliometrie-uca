# Chantier — Barres à facettes homogènes + extraction des ListView (thèses, personnes)

Commencé le 2026-06-07

Issu d'un item TODO_LAURA (« style barre facettes dans labos/thèses : pas homogène aux autres »).

## Contexte

Les pages-listes du front partagent un kit : les classes CSS globales `toolbar` / `toolbar-card` / `toolbar-sticky` ([lib/styles/shared.css](../../interfaces/frontend/src/lib/styles/shared.css)) pour la « barre blanche », plus les composants `FacetDropdown`, `PresenceFilterToggle` et le helper `useFacets`. La « carte blanche » n'est donc pas un composant : c'est l'application de ces classes.

Au-dessus de ce kit, un patron s'est imposé : **une ListView par type de table**, qui regroupe barre à facettes + tableau + pagination (+ bannière de filtre). [`PublicationsListView`](../../interfaces/frontend/src/lib/components/PublicationsListView.svelte) en est la référence (`toolbar-card toolbar-sticky`) et sert déjà six contextes : `/publications`, `journals/[id]`, `laboratories/[id]` (onglet pub), `persons/[id]`, `publishers/[id]`, `subjects/[id]`. `JournalsListView` (journals, publishers/[id], admin/journals) et `PublishersListView` (publishers, admin/publishers) suivent le même patron.

Deux types échappent encore au patron : **thèses** et **personnes**. Leurs composants `ThesesTable` / `PersonsTable` sont des **tables seules** ; la barre à facettes est reconstruite à la main dans chaque page consommatrice. D'où la duplication et les divergences constatées :

- **Onglet thèses de `laboratories/[id]`** : `class="toolbar"` nu — pas de `toolbar-card`, pas de `toolbar-sticky`, pas d'Export CSV. La page autonome `/theses`, elle, a `toolbar-card toolbar-sticky` + Export CSV. C'est le symptôme rapporté.
- **Onglet personnes de `laboratories/[id]`** : `toolbar-card` mais pas `toolbar-sticky`. La page `/persons` a sa propre barre (via `useFacets`).
- **`JournalsListView` / `PublishersListView`** : `toolbar-card` sans `toolbar-sticky` → barre non collante, divergente de `PublicationsListView`.

## Décisions

*(Proposées, questionnables.)*

1. **Pas de composant générique « barre à facettes ».** Le wrapper est déjà réglé par les classes CSS ; ce qui varie d'un type à l'autre, c'est le contenu (quelles facettes, recherche, CSV). Un composant générique config-driven se battrait contre cette variabilité. On reste sur le patron **une ListView par type de table**, déjà validé pour publications/journals/publishers.
2. **Recherche texte + carte/sticky partout ; Export CSV seulement là où l'endpoint existe déjà.** Toute barre porte `toolbar-card toolbar-sticky` et une recherche texte homogènes. Le CSV n'est ajouté **que si un endpoint d'export existe déjà** (cas `theses`) ; on ne crée pas d'endpoint (YAGNI). Le CSV pour les types sans endpoint reste une question ouverte.
3. **Extraire `ThesesListView` et `PersonsListView`** sur le modèle de `PublicationsListView` (barre `toolbar-card toolbar-sticky` + recherche + table + pagination + bannière, + Export CSV quand l'endpoint existe — oui pour `theses`), consommés par la page autonome ET l'onglet de `laboratories/[id]`. Supprime la duplication à la source : l'homogénéité ne peut plus diverger. Ces extractions **remplacent** les barres inline divergentes (onglets thèses/personnes) — donc pas de quick-fix CSS jetable sur ces onglets, l'extraction les corrige directement.
4. **`Journals`/`PublishersListView` : déjà au patron, on les aligne** (sticky + recherche si absente ; CSV uniquement si un endpoint existe déjà). Pas de réécriture, juste l'homogénéisation.
5. **Props minimales pour la variation contextuelle.** La seule vraie différence page autonome ↔ onglet labo est le **labo fixe**. Une prop `labId` optionnelle borne les résultats et masque la facette « Laboratoire » (comme `hasFixedLab` dans `PublicationsListView`). Pas de machinerie de colonnes configurables (`col()`) tant qu'un besoin réel ne se présente pas.

## Phasage

### Phase 1 — Aligner les ListView déjà extraites

- [x] `JournalsListView` + `PublishersListView` : `toolbar-sticky` ajouté (recherche déjà présente dans les deux), alignés sur `PublicationsListView`. Pas de CSV (aucun endpoint, cf. YAGNI) (`afcca67a`)

### Phase 2 — Extraire `ThesesListView`

- [x] Composant `ThesesListView` : barre `toolbar-card toolbar-sticky` + recherche + `ThesesTable` + pagination + Export CSV ; prop `labId` optionnelle (masque la facette Laboratoire + la colonne Labos, borne au labo) ; `urlSync` gatée comme `PublicationsListView` (`26af35f1`)
- [x] `/theses` → wrapper ; onglet thèses de `laboratories/[id]` consomme `ThesesListView` (`labId`, `urlSync=false`) → carte/sticky/CSV homogènes, barre inline supprimée (`26af35f1`)

### Phase 3 — Personnes : homogénéité (sans extraction)

- [x] Homogénéité onglet personnes `laboratories/[id]` : `toolbar-sticky` ajouté (aligné sur `/persons`) (`9053f1bc`)
- [x] Nettoyage : retrait de la bannière « authorships non reliées » de la page labo (code vestigial, doublon de la page admin orphan-authorships) — front + back + `schema.ts` + test (`9053f1bc`)

**Pourquoi les personnes divergent (et le correctif retenu).** Contrairement aux thèses (deux contextes sur le même `/api/publications` filtré par `lab_id`), les personnes ont deux endpoints aux contrats divergents : `/api/persons/directory` (annuaire global `FROM persons`, `total`, facettes via endpoint séparé) vs `/api/laboratories/[id]/persons` (`FROM authorships` scopé labo, `total_persons`, facettes inline). Asymétrie de conception, pas fondamentale. **Décision (Laura) : on aligne — une entité = un endpoint.** On ajoute `lab_id` à l'annuaire et on supprime le bricolage labo, puis on extrait `PersonsListView` comme pour les publications.

### Phase 4 — Backend : aligner l'endpoint personnes sur le modèle publications

- [x] Clause réutilisable `person_in_lab_clause(lab_id)` (`EXISTS authorships → authorship_structures = lab`, rôle author) dans `infrastructure/queries/filters.py` (`7f7b2fc7`)
- [x] `lab_id` ajouté à `DirectoryFilters`/`FacetFilters` + param sur `/api/persons/directory` et `/api/persons/facets` ; `pub_count` scopé labo quand `lab_id` ; facettes scopées (`7f7b2fc7`)
- [x] Tests : annuaire + facettes scopés par `lab_id` (`7f7b2fc7`)

### Phase 5 — Extraire `PersonsListView`

- [x] Composant `PersonsListView` (mirror `Publications`/`ThesesListView`) : barre `toolbar-card toolbar-sticky` + recherche + Identifiants + Fonction/Département/Base RH + `PersonsTable` + pagination ; prop `labId` ; `urlSync` gatée ; via `/api/persons/directory` + `/facets` (`a0163b8b`)
- [x] `/persons` → wrapper ; onglet personnes de `laboratories/[id]` consomme le composant (`labId`, `urlSync=false`) ; barres inline supprimées (`a0163b8b`)

### Phase 6 — Supprimer le bricolage `laboratories/[id]/persons`

- [x] Retrait route + `get_laboratory_persons` + modèles `LaboratoryPersonsResponse`/`LabPersonOut`/`LabPersonsFacets`/`LabPersonsFilters` + `_lab_persons_extra_clauses` + imports + test + regen `schema.ts` (`bcb10dc8`, −500 lignes)

### Vérification

- [x] `svelte-check` sans erreur ; tests backend (labo, annuaire scopé, persons API) verts à chaque phase.
- [ ] Revue visuelle restante côté Laura (page autonome ↔ onglet labo identiques pour thèses et personnes).

## Questions ouvertes

- **Export CSV pour personnes / journaux / éditeurs.** Reporté (YAGNI) : on ne crée aucun endpoint d'export pour ce chantier. Seul `theses` a un endpoint existant et garde son CSV. À rouvrir si un besoin réel se présente — impliquera de créer les endpoints côté backend.
