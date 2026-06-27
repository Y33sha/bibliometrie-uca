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

### Le modèle conceptuel : quatre axes

Toute vue du système est une requête à quatre axes orthogonaux :

1. **Le corpus interrogé** — *ce qu'on compte*. « Nombre de X » : X est le corpus, par défaut les publications, éventuellement les revues ou les éditeurs distincts. Changer de corpus, c'est changer ce que dénombre le `COUNT(DISTINCT …)`. Le compte du corpus *est* la grandeur affichée ; il n'y a pas de « mesure » comme axe séparé.
2. **Les filtres** — les contraintes qui restreignent le corpus (les facettes du haut de page).
3. **Le groupement** — l'axe de ventilation, une *catégorie à analyser* : « nombre de X *par Y* » (par voie d'accès, par type de document, par éditeur…). Un axe ordinal comme l'année n'en est pas : on ne groupe pas par année.
4. **La comparaison** — un second axe, facultatif, *ce que l'on compare* : « nombre de X par Y, *d'un Z à l'autre* » (d'une année à l'autre, d'un laboratoire à l'autre). C'est l'axe naturel de l'année et des entités ; il se déploie en abscisse, le groupement formant l'empilement de chaque barre.

Les quatre onglets de la page de statistiques ne sont donc pas quatre pages, mais quatre **préréglages** d'un même pivot. De ce cadrage découlent les intuitions du chantier. La **liste est le pivot à zéro groupement** (la mesure, ce sont les lignes elles-mêmes) ; le drill-down du graphique vers la liste **pèle un groupement et le convertit en filtre**, jusqu'à ce qu'il ne reste plus de groupement — la liste filtrée. La **cardinalité contraint le rendu** : faible cardinalité (année, accès, type) → axe de graphique ; forte cardinalité (laboratoire, revue, éditeur — des milliers de valeurs) → top N et « Autres », ou table classée, ou simple renvoi vers la liste existante. La **part (empilement à 100 %) est un mode de présentation** indépendant des axes, pas une mesure : « % d'accès ouvert » se lit en comparant par accès puis en aplatissant à 100 %.

## Décisions

Ces décisions sont des orientations proposées, à confirmer ou amender ; seul le contexte ci-dessus est factuel.

1. **Quatre axes orthogonaux, portés par l'URL** : corpus, filtres, groupement, comparaison. S'y ajoutent deux modes de présentation (absolu / part, graphique / table) et un tri (« classer par »), qui ne sont pas des axes. Les préréglages actuels (par année et voie d'accès, top éditeurs, etc.) deviennent des points de départ sur ce moteur, non des branches de code séparées.

2. **Le corpus est l'axe « ce qu'on compte »**, pas une « mesure » distincte. La grandeur affichée est toujours un `COUNT(DISTINCT <corpus>.id)` sur l'ensemble filtré ; il n'y a donc pas de sélecteur de mesure. Le corpus vaut les publications par défaut ; les revues et les éditeurs distincts viennent ensuite (« nombre de revues par éditeur » = corpus *revues*, groupé par éditeur). Une grandeur sort de ce cadre du « compte » : la **somme des frais de publication** (en euros). On l'ignore tant qu'aucun besoin ne l'exige ; le jour venu, elle prendra la forme d'un **mode « somme »** s'ajoutant au compte, et non d'un corpus.

3. **Backend = moteur d'agrégation générique**, conçu comme un constructeur de requête sur un **registre fermé** : chaque dimension et chaque corpus map vers une expression connue, la composition `SELECT <dimensions>, COUNT(DISTINCT <corpus>) … GROUP BY <dimensions>` se fait sur liste blanche. Ce n'est pas du SQL libre — aucune injection possible — mais un assembleur sur vocabulaire borné. Le moteur consolide au passage la clause de filtres, aujourd'hui dupliquée entre les endpoints `by-year`, `publishers`, `journals`, `labs`, `summary`. L'absence d'enjeu temporel fait préférer ce moteur générique à un jeu d'endpoints figés : il n'y a qu'une source de vérité, et l'ajout d'une dimension se fait dans le registre.

4. **Le registre de dimensions est l'artefact central**, partagé entre le constructeur SQL et les sélecteurs de l'interface. Pour chaque dimension : son expression, sa jointure éventuelle, son **grain** (une publication rattachée à deux laboratoires compte dans les deux : grouper par une dimension qui démultiplie impose `count(distinct publication_id)`), sa cardinalité, son caractère ordinal. La gestion du grain est la vraie difficulté du backend, et elle existe quelle que soit l'approche.

5. **Liste = pivot à zéro groupement**, drill-down = conversion d'un groupement en filtre. Le « bouton Publications » ad hoc disparaît au profit d'un changement de lentille qui porte le filtre **complet** (sans `doc_type` forcé).

6. **Le tableau de bord renvoie vers les listes, il ne les recrée pas.** Le va-et-vient est l'objectif : du graphique vers la liste filtrée, et retour. Une table dans le tableau de bord ne se justifie que pour ce qu'une liste de publications ne sait pas rendre — typiquement un **classement d'entités par agrégat** (les laboratoires les plus ouverts). Pour le détail, le lien renvoie vers la liste existante en transmettant les filtres, plutôt que de réimplémenter cette liste dans le tableau de bord.

7. **Accès ouvert : une part, pas une mesure.** Vocabulaire générique « ouvert / fermé / sous embargo » par défaut (le même que la fiche détail d'une publication) ; les huit voies (gold, green, etc.) à la demande, par comparaison. Le « % d'accès ouvert » n'est pas une mesure-axe : c'est la **comparaison par accès aplatie à 100 %** sur un graphique, ou une **colonne triable** dans un classement d'entités. Les colonnes numériques par valeur de `oa_status` sont retirées des tables (la barre de répartition suffit ; le détail relève du drill-down).

8. **Rendu : modes de présentation et garde-fous de cardinalité.** Groupement simple → barres (absolu) ou camembert (part). Comparaison → histogramme empilé, dont l'orientation suit la lisibilité des libellés (les années en abscisse, les entités à libellé long en ordonnée). La bascule absolu / part est une case à cocher qui aplatit l'empilement à 100 %. Un bouton « classer par » trie la ventilation. La cardinalité ne dicte pas le rendu mais contraint le faisable : forte cardinalité → top N et barre « Autres », table seulement si c'est le seul rendu possible, sinon renvoi vers la liste. L'export suit le rendu : table → CSV (valeurs exactes), graphique → PNG (l'histoire visuelle).

9. **L'URL reste le siège de l'état**, avec omission des valeurs par défaut et clés courtes pour rester compact. Les vues nommées (configuration persistée côté serveur, référencée par identifiant) sont différées : elles répondront au seul cas réellement volumineux (multi-sélections de dizaines d'identifiants) et au besoin de rapports récurrents.

## Phasage

### Phase 0 — Registre des dimensions et des mesures

- [x] Recenser les dimensions groupables et filtrables, et pour chacune : expression, jointure, grain (démultiplication ou non), cardinalité, caractère ordinal. → registre pur `domain/stats/pivot.py` : année · accès · voie OA · type · laboratoire · APC, chaque entrée portant cardinalité, ordinal, grain (`multiplies`) et rôles `groupable`/`filterable` ; liaison SQL côté infrastructure (5b741330, 9aaa73fb).
- [x] Recenser les mesures. → le registre ne porte qu'un compte : `nombre de publications` (`COUNT(DISTINCT)`). Le taux d'accès ouvert n'est pas une mesure (il se lit comme part à 100 % ou colonne de classement) ; un éventuel mode « somme » (frais de publication) viendra plus tard. Compter d'autres corpus (revues, éditeurs) reste une question ouverte (36eba95c).

### Phase 1 — Moteur d'agrégation générique (backend)

- [x] Endpoint unique d'agrégation paramétré par mesure, groupements et filtres, composé sur le registre. → `GET /api/stats/pivot` + `/api/stats/pivot/schema`, composition sur liste blanche, 400 sur clé inconnue (5b741330).
- [x] Gestion du grain : `count(distinct publication_id)` dès qu'un groupement démultiplie. → mesures `COUNT(DISTINCT p.id)` (5b741330).
- [ ] Consolidation de la clause de filtres aujourd'hui dupliquée entre les endpoints de statistiques. → le pivot réutilise les clauses de `filters.py` ; reste à y rallier `summary`/`publishers`/`journals`/`labs`, encore dupliquées (rejoint le dé-hardcode `doc_type`, Phase 3).

### Phase 2 — Reformulation de l'accès ouvert

- [x] Taux d'accès ouvert lu comme part (et non comme mesure) ; vocabulaire générique ouvert / fermé / sous embargo par défaut. → vocabulaire `oa_access` (ouvert / embargo / fermé / indéterminé) = découpage par défaut de l'histogramme, les 8 voies à la demande via `oa_voie` ; le taux se lit via la bascule absolu / part (5b741330, 24b8158f, 36eba95c).
- [x] Retrait des colonnes par valeur de `oa_status` des tables ; voies détaillées à la demande. → fait (2b6beb46) ; la barre de répartition suffit, le détail chiffré relève du pivot.

### Phase 3 — Interface du pivot

- [ ] Sélecteurs de mesure, de mode (absolu / part), de groupement (primaire et secondaire), de rendu (graphique / table).
  - [x] **groupement** : sélecteurs « Grouper par » (la catégorie à analyser — accès, voie, type — empilée dans chaque barre ; un axe ordinal comme l'année en est exclu) et « Comparer par » (l'axe déployé en abscisse, où figure l'année, facultatif, excluant la dimension prise comme groupement). Défaut : groupé par accès, comparé par année — barres par année, empilées par accès. Sans comparaison, le groupement passe en abscisse. Options lues du schéma du registre (24b8158f, 02cb8180, fc3ec564, e2da7875).
  - [x] **comparaison à forte cardinalité** : le laboratoire devient une dimension de pivot groupable (jointures de rattachement, grain `COUNT(DISTINCT)`) offerte en « Comparer par ». L'abscisse est **paginée** (10 par page, triées par total décroissant ; page portée par l'URL) plutôt que tronquée, et passe en **barres horizontales** pour les libellés longs. Le libellé est l'acronyme ou le nom du laboratoire (bd5f8f3e, 96541a98, 64e64de7). Revue et éditeur en comparaison restent à brancher de la même façon.
  - [x] **corpus / mesure** : le graphe est toujours le compte de publications (barres empilées) ; pas de sélecteur de mesure. La mesure-ratio « % d'accès ouvert » est retirée du registre — le taux se lit via la bascule absolu / part, le découpage par accès portant déjà l'information (32d26a4c, 36eba95c).
  - [x] **mode** absolu / part : case à cocher « Part (%) » qui aplatit l'empilement à 100 % ; portée par l'URL (clé `mode`), visible seulement avec une comparaison (71394885).
  - [ ] **rendu** graphique / table.
- [x] Bascule d'une dimension entre filtre et groupement (un groupement catégoriel sort des facettes ; un groupement ordinal comme l'année reste filtrable en plage).
  - [x] **cadre posé** : rôles `groupable`/`filterable` au registre + `applicable_facets` (règle G : un groupement catégoriel sort des facettes, l'ordinal reste), testé (9aaa73fb, 36eba95c).
  - [x] **dériver la barre de facettes** côté UI (montrer / masquer un dropdown selon le groupement courant) sur les facettes existantes (année / labo / OA / APC) — miroir TS de la règle G sur l'onglet OA ; grouper par voie OA retire la facette « Voies OA » (9fb2a2ac).
  - [x] **facette « Type de document »** : comptes dans `/api/stats/facets` + dropdown groupé par familles (même base que la liste des publications), défaut famille « Publications » (08487681).
  - [x] **dé-hardcoder `doc_type`** dans `summary`/`publishers`/`journals`/`labs` : passé en filtre, plus aucun hardcode `article,review` côté stats ; le lien « Voir les publications » porte la sélection de types (08487681).
- [ ] Préréglages (par année et voie d'accès, top éditeurs…) comme points de départ.

### Phase 4 — Va-et-vient liste ↔ tableau de bord

- [ ] Drill-down du graphique vers la liste : un clic pèle un groupement en filtre.
- [ ] Changement de lentille de la liste vers le tableau de bord, à filtre constant.
- [ ] Convergence vers une page unifiée à lentilles plutôt que deux pages pontées.

### Phase 5 (ultérieure) — Vues nommées

- [ ] Persistance et partage de configurations de pivot, pour les rapports récurrents et les sélections volumineuses.

## Items TODO liés (à intégrer quelque part)
* [x] ajouter facettes sur dashboards pour générer dynamiquement les graphiques → l'histogramme OA est piloté par le pivot, sa ventilation est un choix (24b8158f) ; la dérivation de la barre de facettes elle-même est en cours (Phase 3).
* [x] permettre des ventilations par labo (taux d'open access) → « Comparer par → Laboratoire » donne les laboratoires en abscisse paginée, empilés par le groupement (accès…) ; en mode part, le taux d'ouverture par laboratoire. Cela a permis de supprimer l'onglet Laboratoires et sa chaîne backend `/api/stats/labs` (e8af81ba).

## Questions ouvertes

- **Dimensions de départ** : quel jeu rendre groupable et filtrable d'emblée (année, voie d'accès, type, éditeur, revue, laboratoire) ? C'est ce choix qui dimensionne le registre et le premier moteur.
- **Corpus au-delà des publications** : faut-il compter d'autres corpus (revues, éditeurs distincts) sur le tableau de bord, et pour quels besoins ?
- **Page unifiée à lentilles ou deux pages pontées** : viser d'emblée une page unique avec commutateur de lentille, ou converger par étapes (d'abord rendre le pont bidirectionnel et filtre-complet, puis embarquer la visualisation dans la liste) ?
- **Périmètre des types de documents** : le taux d'accès ouvert n'a de sens que pour certains types ; rendre le filtre `doc_type` explicite (visible) plutôt que caché en dur.
- **Politique d'URL** : seuil de multi-sélection au-delà duquel basculer sur les vues nommées.

## Liens

- Page de statistiques actuelle : `interfaces/frontend/src/routes/stats/+page.svelte`.
- Lentille liste réutilisable : `interfaces/frontend/src/lib/components/PublicationsListView.svelte`.
- Composables d'état partagé : `interfaces/frontend/src/lib/composables/useUrlFilters.svelte.ts`, `useFacets.svelte.ts`, `usePaginatedFetch.svelte.ts`.
- Endpoints de statistiques actuels : `/api/stats/summary`, `/by-year`, `/publishers`, `/journals`, `/labs`, `/facets`.
