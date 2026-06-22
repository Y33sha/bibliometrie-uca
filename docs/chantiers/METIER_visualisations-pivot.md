# Chantier — Visualisations dynamiques (pivot listes ↔ tableaux de bord)

Commencé le 2026-06-22

Repenser la page de statistiques et, plus largement, unifier la navigation entre les vues « liste » (les publications une à une) et les vues « tableau de bord » (les agrégats), de sorte que chaque graphique mène au détail des entités qu'il agrège, et que chaque liste filtrée donne accès à des visualisations qui conservent ses facettes.

## Contexte

### L'insatisfaction de départ

La page de statistiques est la première page construite, et elle remplit son office (taux d'accès ouvert, classements d'éditeurs et de revues) sans satisfaire pleinement. Trois irritants concrets : le taux d'accès ouvert est exprimé en plusieurs tranches correspondant aux valeurs de `oa_status` (diamond, gold, hybrid, bronze, green, embargoed, closed, unknown), un vocabulaire de spécialiste ; les tables sont surchargées de colonnes, avec un niveau de détail qui ne se justifie pas toujours (un compte de publications par valeur de `oa_status`, en plus de la barre de répartition visuelle) ; le passage vers la liste des publications se fait par un bouton ad hoc qui transfère les filtres actifs mais force `doc_type=article,review` en dur.

### L'objectif

Un va-et-vient entre listes et tableaux de bord, ces derniers étant compris comme des agrégations d'une liste filtrée. Deux directions à rendre systématiques : du graphique vers la liste (cliquer un agrégat ouvre le détail des publications correspondantes, à la manière du lien d'InCites vers Web of Science) ; de la liste vers la visualisation (toute liste, filtrée ou non, donne accès à des graphiques dynamiques qui conservent les facettes actives).

### L'existant porte déjà l'essentiel

L'architecture frontend supporte une grande part de cet objectif sans que ce soit nommé. `PublicationsListView` est une lentille « liste » réutilisable, embarquée dans six contextes (la page publications, et l'onglet `tab=publications` des pages laboratoire, personne, revue, éditeur, sujet), chacun avec des filtres externes et une synchronisation d'URL. La page de statistiques est une lentille « tableau de bord » sur un état de filtre partagé (années, laboratoires, accès ouvert, frais de publication, éditeur, revue), avec un enchaînement éditeur → revues → détail et un fil d'Ariane. Les deux lentilles s'appuient sur les mêmes briques (`useUrlFilters`, `useFacets`, `usePaginatedFetch`, `FacetDropdown`) et **portent tout leur état dans l'URL**.

### Le modèle conceptuel établi : le pivot

Toute vue du système est une requête à trois rôles : une **mesure** (ce qu'on agrège — aujourd'hui toujours le nombre de publications), un **groupement** (les axes de ventilation — codés en dur par onglet : année croisée avec `oa_status`, ou éditeur, ou revue, ou laboratoire), et des **filtres** (les contraintes du corpus — les facettes du haut de page). Les quatre onglets de la page de statistiques ne sont donc pas quatre pages, mais quatre **préréglages de groupement** d'un même pivot.

De ce cadrage découlent plusieurs propriétés qui unifient les intuitions du chantier. La **liste est le cas du pivot à zéro groupement** (la mesure, ce sont les lignes elles-mêmes) ; le drill-down du graphique vers la liste devient alors une opération algébrique propre : cliquer un agrégat **pèle une dimension de groupement et la convertit en filtre**, jusqu'à ce qu'il ne reste plus de groupement — c'est-à-dire la liste filtrée. La **cardinalité d'une dimension contraint la faisabilité** d'un rendu : les dimensions à faible cardinalité (année, voie d'accès, type, source) conviennent à des axes de graphique, les dimensions à forte cardinalité (éditeur, revue, sujet, personne — des milliers de valeurs) appellent une table classée ou un graphique tronqué aux N premières valeurs. Le rapport **absolu / taux est un axe de normalisation** indépendant du groupement. Le **rendu graphique / table est un choix par vue**, souvent dicté par le besoin d'export.

## Décisions

Ces décisions sont des orientations proposées, à confirmer ou amender ; seul le contexte ci-dessus est factuel.

1. **Modèle pivot à axes orthogonaux**, tous portés par l'URL : mesure, mode (absolu ou part), groupement primaire et secondaire, rendu (graphique ou table), filtres. Les préréglages actuels (par année et voie d'accès, top éditeurs, etc.) deviennent des points de départ sur ce moteur, non des branches de code séparées.

2. **Backend = moteur d'agrégation générique**, conçu comme un constructeur de requête sur un **registre fermé** : chaque dimension et chaque mesure map vers une expression connue, la composition `SELECT <dimensions>, <mesure> … GROUP BY <dimensions>` se fait sur liste blanche. Ce n'est pas du SQL libre — aucune injection possible — mais un assembleur sur vocabulaire borné. Le moteur consolide au passage la clause de filtres, aujourd'hui dupliquée entre les endpoints `by-year`, `publishers`, `journals`, `labs`, `summary`. L'absence d'enjeu temporel fait préférer ce moteur générique à un jeu d'endpoints figés : il n'y a qu'une source de vérité, et l'ajout d'une dimension se fait dans le registre.

3. **Le registre de dimensions est l'artefact central**, partagé entre le constructeur SQL et les sélecteurs de l'interface. Pour chaque dimension : son expression, sa jointure éventuelle, son **grain** (une publication rattachée à deux laboratoires compte dans les deux : grouper par une dimension qui démultiplie impose `count(distinct publication_id)`), sa cardinalité, son caractère ordinal. Un petit registre de mesures l'accompagne. La gestion du grain est la vraie difficulté du backend, et elle existe quelle que soit l'approche.

4. **Liste = pivot à zéro groupement**, drill-down = conversion d'un groupement en filtre. Le « bouton Publications » ad hoc disparaît au profit d'un changement de lentille qui porte le filtre **complet** (sans `doc_type` forcé).

5. **Accès ouvert reformulé.** Par défaut, le vocabulaire générique « ouvert / fermé / sous embargo » (le même que la fiche détail d'une publication) et un taux phare ; les voies détaillées (gold, green, etc.) restent accessibles à la demande, par changement de mesure ou par groupement secondaire. « % d'accès ouvert » devient une **mesure nommée de plein droit**, car c'est l'indicateur phare et qu'on le veut souvent sans avoir à grouper par voie puis sommer les voies ouvertes. Les colonnes numériques par valeur de `oa_status` sont retirées des tables (la barre de répartition suffit ; le détail relève du drill-down).

6. **Graphique / table : un commutateur par vue.** La cardinalité ne dicte pas le rendu, elle contraint le faisable : forte cardinalité → table classée, ou graphique tronqué aux N premières valeurs (avec un tri par la mesure et éventuellement une barre « Autres »). Dans le faisable, le choix est libre et sert l'export : table → CSV (valeurs exactes), graphique → PNG (l'histoire visuelle).

7. **Deux sens de « taux » à distinguer.** D'une part la **normalisation d'une ventilation** (empilement à 100 %) : quand un groupement secondaire partage un tout, basculer de l'absolu à la part donne la proportion de chaque valeur — simple bascule de présentation, valable pour tout secondaire catégoriel. D'autre part la **mesure-ratio** (« % d'accès ouvert » = publications ouvertes sur total) qui effondre une dimension catégorielle en un numérateur sur un dénominateur et donne une courbe plutôt qu'un empilement. L'interface offre les deux : la bascule absolu / part sur toute ventilation, et les mesures-ratios nommées.

8. **L'URL reste le siège de l'état**, avec omission des valeurs par défaut et clés courtes pour rester compact. Les vues nommées (configuration persistée côté serveur, référencée par identifiant) sont différées : elles répondront au seul cas réellement volumineux (multi-sélections de dizaines d'identifiants) et au besoin de rapports récurrents.

## Phasage

### Phase 0 — Registre des dimensions et des mesures

- [ ] Recenser les dimensions groupables et filtrables, et pour chacune : expression, jointure, grain (démultiplication ou non), cardinalité, caractère ordinal.
- [ ] Recenser les mesures : agrégats (nombre de publications, somme des frais de publication, nombre de revues distinctes…) et mesures-ratios nommées (% d'accès ouvert, et ultérieurement % avec frais de publication, % déposé en archive ouverte…).

### Phase 1 — Moteur d'agrégation générique (backend)

- [ ] Endpoint unique d'agrégation paramétré par mesure, groupements et filtres, composé sur le registre.
- [ ] Gestion du grain : `count(distinct publication_id)` dès qu'un groupement démultiplie.
- [ ] Consolidation de la clause de filtres aujourd'hui dupliquée entre les endpoints de statistiques.

### Phase 2 — Reformulation de l'accès ouvert

- [ ] Mesure nommée « % d'accès ouvert » ; vocabulaire générique ouvert / fermé / sous embargo par défaut.
- [ ] Retrait des colonnes par valeur de `oa_status` des tables ; voies détaillées à la demande.

### Phase 3 — Interface du pivot

- [ ] Sélecteurs de mesure, de mode (absolu / part), de groupement (primaire et secondaire), de rendu (graphique / table).
- [ ] Bascule d'une dimension entre filtre et groupement (un groupement catégoriel sort des facettes ; un groupement ordinal comme l'année reste filtrable en plage).
- [ ] Préréglages (par année et voie d'accès, top éditeurs…) comme points de départ.

### Phase 4 — Va-et-vient liste ↔ tableau de bord

- [ ] Drill-down du graphique vers la liste : un clic pèle un groupement en filtre.
- [ ] Changement de lentille de la liste vers le tableau de bord, à filtre constant.
- [ ] Convergence vers une page unifiée à lentilles plutôt que deux pages pontées.

### Phase 5 (ultérieure) — Vues nommées

- [ ] Persistance et partage de configurations de pivot, pour les rapports récurrents et les sélections volumineuses.

## Questions ouvertes

- **Dimensions et mesures de départ** : quel jeu rendre groupable et mesurable d'emblée (année, voie d'accès, type, source, éditeur, revue, laboratoire ; nombre de publications, % d'accès ouvert, frais de publication) ? C'est ce choix qui dimensionne le registre et le premier moteur.
- **Page unifiée à lentilles ou deux pages pontées** : viser d'emblée une page unique avec commutateur de lentille, ou converger par étapes (d'abord rendre le pont bidirectionnel et filtre-complet, puis embarquer la visualisation dans la liste) ?
- **Périmètre des types de documents** : le taux d'accès ouvert n'a de sens que pour certains types ; rendre le filtre `doc_type` explicite (visible) plutôt que caché en dur.
- **Politique d'URL** : seuil de multi-sélection au-delà duquel basculer sur les vues nommées.

## Liens

- Page de statistiques actuelle : `interfaces/frontend/src/routes/stats/+page.svelte`.
- Lentille liste réutilisable : `interfaces/frontend/src/lib/components/PublicationsListView.svelte`.
- Composables d'état partagé : `interfaces/frontend/src/lib/composables/useUrlFilters.svelte.ts`, `useFacets.svelte.ts`, `usePaginatedFetch.svelte.ts`.
- Endpoints de statistiques actuels : `/api/stats/summary`, `/by-year`, `/publishers`, `/journals`, `/labs`, `/facets`.
