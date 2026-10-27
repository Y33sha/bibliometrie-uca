# Cohérence graphique, responsivité et accessibilité du frontend

## Contexte

Audit du 2026-10-26 : parcours Playwright en 1440, 800 et 390 px de large, audit axe-core, parcours clavier.

**En-têtes de page.** Quatre modèles coexistent.

| Pages | En-tête |
|---|---|
| Publications, Labos, Chercheurs, Thèses, Éditeurs, Publications en série, Monographies | barre d'outils, sans titre visible |
| Sujets | H1 1,4rem et phrase de description |
| Problèmes HAL | H1 ~2rem et encart d'information |
| Pages de détail | fil d'Ariane et H1 (classes `entity-*`) |

**Barres d'outils des listes.** Chaque vue de liste compose sa barre : `PublicationsListView`, `PersonsListView`, `ThesesListView`, `PublishersListView`, `SerialsListView`, `MonographsListView`, `structures/+page.svelte`, les pages Problèmes HAL.

- Champ de recherche pleine largeur sur les publications. Ailleurs, sa largeur varie de 220 à 350 px.
- Libellé « Filtrer par : » seulement sur Publications et Statistiques.
- Compteur à gauche de l'export sur Publications et Thèses, aligné à droite sur les autres listes, sous la recherche sur Sujets.
- Export CSV seulement sur Publications et Thèses ; menu de colonnes « ⋯ » aussi. L'API sert seulement ces deux exports (`/api/publications/export.csv`, `/api/publications/export-theses.csv`).
- Champ « Occurrences min » de Sujets sans le style des autres contrôles.
- Placeholders terminés par « ... », « … », « . » ou sans ponctuation.

**Libellés.** Chaque vue déclare ses libellés de facettes et de colonnes. `PublicationsListView` écrit deux fois le libellé d'une colonne : « Année » dans le menu de colonnes, « An. » dans l'en-tête.

- Facettes : « Années » ou « Année », « Laboratoires » ou « Laboratoire » selon la liste.
- Colonnes : « An. » ou « Année », « Publis » ou « Publications », « Labo(s) » ou « Laboratoire(s) ».
- Dashboards : « Types de publications » (éditeur) ou « Types de documents » (publication en série) ; « Sujets dominants » ou « Sujets principaux ».
- Trois noms pour une page Problèmes HAL : menu « Doublons auteurs », H1 « Doublons d'auteurs HAL », titre du navigateur « Doublons comptes HAL ». De même, menu « Affiliations suspectes » et H1 « Conflits d'affiliations HAL ».
- Abréviations au menu : « Doublons publis », « Manques collections ».
- Titres du navigateur « Structures » et « Personnes », menu « Labos » et « Chercheurs » (voir [Administration et navigation](UI_administration-et-navigation.md), question « Vocabulaire des listes »).
- Anneau des collaborations : « Domestique » pour « National ».

**Composants.**

- Identifiants : ISSN en police proportionnelle grise (liste des publications en série), ISBN en `--mono` noir (liste des monographies). Identifiant HAL en pastille bleu foncé sur les pages Problèmes HAL, identifiants en pastille teal clair ailleurs.
- Barres horizontales : deux styles sur la fiche structure. Les pays partenaires sont un graphique Chart.js à axe et barres épaisses, les sujets des barres fines arrondies (`SubjectBars`).
- Anneau des collaborations : libellé blanc sur la part grise claire, illisible.
- Liste des publications : en-tête « Accès / Liens » sur deux lignes ; bouton plein « Texte intégral » sur chaque ligne, plus visible que le titre ; barre d'outils collante et en-tête de tableau non collant.
- Liste des éditeurs : filets interrompus dans la colonne « Préfixes DOI » ; « Type inconnu » écrit en toutes lettres, cellule vide dans les autres listes.
- Manques collections : une carte par publication. Le titre passe à la ligne selon la présence du badge « Hors collections ».
- Fiche publication : « Résumé » seul titre de section sans icône ; « Mots-clés libres » avec son propre style ; « Accès fermé » semblable à un bouton désactivé.
- 46 couleurs hexadécimales en dur dans 10 composants, dont 16 dans `PublicationHeader.svelte` et 11 dans `DoughnutChart.svelte`.

**Responsivité (390 px).**

- Défilement horizontal de la page : `/structures` (tableau de 712 px), `/subjects` (champ « Occurrences min »), `/subjects/[id]` (tableau).
- Tableaux coupés à droite, sans indice de défilement. Sur les publications, le titre tient dans ~90 px ; type, année et DOI gardent leur largeur.
- Publications : le compteur tronque le champ de recherche.
- Statistiques : quand les sélecteurs passent à la ligne, leurs séparateurs verticaux restent en fin de ligne.
- Fiche publication : fil d'Ariane coupé avec « › » en tête de ligne ; tiret entre revue et éditeur seul en fin de ligne.
- Fiche structure : onglet « Collaborations » hors de l'écran, sans indice de défilement ; libellé « Tutelles » séparé de ses valeurs.
- Au-dessus de 940 px, les sous-menus de navigation s'ouvrent au survol seulement : ils restent fermés sur une tablette en paysage.

**Accessibilité.**

- Sous-menus de navigation (Référentiels, Problèmes HAL, Administration, compte) ouverts par `:hover` seulement. Entrée sur le bouton laisse le menu fermé. Boutons sans `aria-expanded` ni `aria-haspopup`.
- Aucun `<main>`. `role="navigation"` sur les `div` des sous-menus, à l'intérieur du `<nav>` : repères en double.
- Aucun lien d'évitement. Le focus initial de chaque liste est dans la recherche, après la navigation.
- Le nom du site est un H1 : chaque page a deux H1. Sur les fiches, les titres de section passent de H1 à H3.
- Contrastes sous 4,5:1 :

  | Élément | Couleurs | Ratio |
  |---|---|---|
  | Liens de navigation | `#e0ecec` sur `#2f7f7f` | 3,89 |
  | Lien de navigation actif | blanc sur `#549696` | 3,39 |
  | Pastilles de tutelle, années (Manques collections) | `#6b7280` sur `#eef0f2` | 4,23 |
  | Badge « Soutenue » | `#2a7d4f` sur `#e6f4ec` | 4,46 |
  | Badge « Hors collections » | `#e65100` sur `#fff3e0` | 3,45 |

  Le lien « Connexion », à opacité 0,6, est plus pâle encore.
- `select` de Manques collections sans nom accessible.
- Graphe des sujets : éléments focusables imbriqués dans le SVG.
- svelte-check : 9 avertissements d'accessibilité. Des `div` cliquables sans gestion du clavier dans `FacetDropdown`, `ColumnMenu`, `Modal`, `DialogHost`, `EntityFilter`, `PresenceFilterToggle` et Affiliations ; un dialogue sans `tabindex` dans Qualité de la détection. `npm run check` échoue seulement sur les erreurs.

**API de navigation SvelteKit dépréciées** (avertissements en console).

- `goto(..., { replaceState: true })` dans `routes/+page.svelte`, `admin/+layout.svelte`, `publications/+page.svelte`, `TabNav.svelte`, `pagination.ts`, `useUrlFilters.svelte.ts`.
- `replaceState()` de `$app/navigation` dans 10 pages, qui synchronisent chacune leur URL à la main : les quatre pages Problèmes HAL, `journals`, `persons`, `admin/addresses`, `admin/countries`, `admin/feedback`, `admin/orphan-contributions`.

**Administration.**

- Titre de page en H1 (Pays, Contributions orphelines), en H2 (Configuration, Pipeline, Qualité de la détection) ou absent (Affiliations). Menu « Logs », titre « Pipeline ».
- Configuration en colonne centrée de ~800 px, les autres pages en pleine largeur.
- Cartes bordées sur Pipeline, Affiliations et Qualité de la détection.
- Lien « ← Retour aux personnes » sur Contributions orphelines, fil d'Ariane sur Qualité de la détection.
- Chiffres clés de Qualité de la détection en cartes à liseré coloré, hors `KeyFigures`. Nombres sans séparateur de milliers (« 26699 ») et pourcentage à point décimal (« 99.3% ») ; ailleurs « 415 705 » et « 63 % ».
- Encart d'avertissement orange (Contributions orphelines, liste des personnes), encart d'information teal ailleurs.
- `select` natifs non stylés (Affiliations, Pays). Sélecteur de pays par ligne réduit à « · ⌄ ». Boutons de rejet et de validation en « X » et « ✓ ».
- Adresses en `--mono` sur Qualité de la détection, en police courante sur Affiliations et Pays.
- Pastille de source « OA » pour OpenAlex, homonyme d'open access.
- Abréviations : « publis », « Publis », « Labo(s) ».
- En 390 px : défilement horizontal de la page sur Configuration, Pipeline, Affiliations, Pays et Contributions orphelines. Sur Affiliations, les pastilles des compteurs deviennent des ronds sur plusieurs lignes.
- Cases à cocher sans libellé (Affiliations, Pays, Contributions orphelines). `select` sans nom accessible (Configuration, Affiliations, Pays, Qualité de la détection). Case à cocher dans un en-tête `role="button"` (Affiliations).
- Contrastes : lien « admin » de la barre (3,77), pastilles de pays (4,46), valeur d'avertissement de Qualité de la détection (2,37), lien des contributions orphelines (3,45).

## Décisions

- **Un composant d'en-tête de page** pour les pages hors fiche d'entité : H1 et description facultative, une seule taille de titre.
- **Un composant de barre d'outils de liste** : recherche, compteur, actions, facettes, filtres actifs. Même disposition et même largeur de recherche sur toutes les listes.
- **Un registre de libellés** pour les facettes et les colonnes, lu par le menu de colonnes et par l'en-tête. Libellés entiers, sans abréviation. Facettes au pluriel.
- **Un nom par page**, identique dans le menu, le H1 et le titre du navigateur. Le H1 et le titre d'une page Problèmes HAL comportent « HAL ». Les pages des structures et des personnes s'appellent « Labos » et « Chercheurs ».
- **Placeholders** sans ponctuation finale.
- **Un seul style d'identifiant**, en `--mono`, sur les listes comme dans les en-têtes d'entité.
- **Valeur absente** : cellule vide.
- **Export CSV sur toutes les listes.** Menu de colonnes sur les listes à nombreuses colonnes.
- **Aucun défilement horizontal de la page**, à toutes les largeurs. Un tableau trop large défile dans son conteneur, avec un indice visuel au bord.
- **Écriture de l'URL** par `replaceQuery` et `setQueryParam` (`lib/url.ts`), qui appellent `goto(url, { replace: true, reset: false })`.
- **Sous-menus de navigation** ouverts au clic, au clavier et au survol ; fermés par Échap et par un clic extérieur.
- **Structure de page** : un `<main>`, un lien d'évitement, un seul H1 par page, titres de section en H2 sur les fiches. Le nom du site est hors des titres. Le H1 des listes est réservé aux lecteurs d'écran.
- **Aucun focus automatique au chargement d'une page.** Seul un champ ouvert par une action le prend : édition en place, sélecteur, filtre ajouté.
- **Contraste de 4,5:1 au minimum** pour tout texte, navigation comprise.
- **Nombres au format français** : séparateur de milliers, virgule décimale, espace avant « % ».
- **Un style d'encart par niveau** : information, avertissement.
- **Pages d'administration aux conventions des pages publiques** : en-tête de page, barre d'outils, un seul niveau de contenant, fil d'Ariane, contrôles stylés.
- **Couleurs en dur restantes** remplacées par les variables de `shared.css`.

## Phasage

### 1. Navigation et structure de page

- [x] Sous-menus au clic et au clavier, `aria-expanded`, fermeture par Échap, clic extérieur et sortie du focus ; suppression des `role="navigation"` internes
- [x] `<main>`, lien d'évitement, nom du site hors des titres, H1 des listes, de Statistiques et d'Affiliations réservé aux lecteurs d'écran ; titres de Configuration, Pipeline et Qualité de la détection en H1
- [x] Focus automatique retiré des recherches de page ; sur Affiliations, le champ d'un filtre texte ajouté prend le focus
- [x] Contraste des liens de navigation, du lien actif et du lien « Connexion » : barre publique en `#246868`

### 2. API de navigation SvelteKit

- [x] `replaceQuery` et `setQueryParam` dans `lib/url.ts`, utilisés par `useUrlFilters`, `pagination.ts`, `TabNav` et les 10 pages
- [x] Redirections de `routes/+page.svelte` et `admin/+layout.svelte` en `goto(..., { replace: true })`

### 3. Libellés

- [x] Registre des libellés des colonnes et des filtres communs à plusieurs listes (`columnLabels`, `filterLabels` dans `lib/labels.ts`) ; menu de colonnes et en-têtes sur le registre
- [x] Pages Problèmes HAL : « Comptes auteur en double », « Dépôts en double », « Publications absentes des collections », « Affiliations divergentes »
- [x] Titres du navigateur et H1 « Labos » et « Chercheurs »
- [x] « National » à la place de « Domestique » ; « Sujets principaux » et « Types de documents » sur les dashboards d'éditeur et de publication en série
- [x] Placeholders

### 4. En-tête de page et barre d'outils

- [x] Composant d'en-tête de page : Problèmes HAL, administration
- [x] Composant de barre d'outils : toutes les listes, pages Problèmes HAL comprises ; champ « Occurrences min » au style des contrôles
- [x] Export CSV de chaque liste, API comprise

### 5. Composants

- [x] Style d'identifiant unique (ISSN, ISBN, HAL)
- [ ] Rendu des barres des dashboards (voir Questions ouvertes)
- [x] Libellés de l'anneau lisibles sur toutes les parts
- [ ] Liste des publications : en-tête « Accès / Liens », poids du bouton « Texte intégral », en-tête de tableau collant
- [x] Liste des éditeurs : filets de la colonne des préfixes, valeur absente en cellule vide
- [ ] Manques collections en tableau
- [ ] Fiche publication : titres de section homogènes, bouton « Accès fermé »
- [ ] Libellés du statut HAL de l'onglet Publications d'un labo servis par l'API : le badge de `PublicationsListView` répète `HAL_DEPOSIT_STATUS_LABELS`

### 6. Accessibilité restante

- [ ] Contrastes des pastilles de tutelle, des années, des badges « Soutenue » et « Hors collections »
- [x] Nom accessible du `select` de Manques collections
- [ ] Graphe des sujets sans éléments focusables imbriqués
- [ ] Titres de section des fiches en H2
- [ ] Avertissements d'accessibilité de svelte-check

### 7. Couleurs en dur

- [ ] `PublicationHeader.svelte`, `DoughnutChart.svelte` et les 8 autres composants sur les variables

### 8. Administration

- [x] En-tête de page ; noms de page (« Logs » et « Pipeline »)
- [ ] Pipeline, Affiliations, Qualité de la détection sans cartes ; Configuration en pleine largeur
- [x] Fil d'Ariane sur Contributions orphelines
- [ ] Chiffres clés de Qualité de la détection en `KeyFigures` ; format des nombres
- [ ] Contrôles stylés ; sélecteur de pays par ligne, boutons de rejet et de validation
- [ ] Pastille de source OpenAlex distincte de l'open access ; abréviations
- [ ] Libellés des cases à cocher et des `select` ; en-tête cliquable d'Affiliations sans contrôle imbriqué ; contrastes

### 9. Responsivité

- [ ] Aucun défilement horizontal de la page : `/structures`, `/subjects`, `/subjects/[id]`, Configuration, Pipeline, Affiliations, Pays, Contributions orphelines
- [ ] Indice de défilement au bord des tableaux et des onglets
- [ ] Barre d'outils des publications, séparateurs de la page Statistiques
- [ ] Fil d'Ariane et ligne revue / éditeur de la fiche publication
- [ ] Libellé « Tutelles » solidaire de ses valeurs ; compteurs d'Affiliations

### 10. Audit final

- [ ] Audit axe-core des pages publiques et d'administration

## Questions ouvertes

- **Rendu des barres des dashboards.** Deux techniques coexistent : Chart.js (`BarChart`, `DoughnutChart`, `PublicationsByYearChart`, page Statistiques, carte) et HTML (`SubjectBars`, `OaBar`). Chart.js partout : les libellés d'axe sont du texte peint dans le canvas, inaccessible au clavier et aux lecteurs d'écran ; seules les barres répondent au clic. Partage par usage : les classements qui mènent à une page (sujets, pays partenaires) en listes de liens HTML, les autres graphiques en Chart.js.
- **Dashboards d'éditeur et de publication en série** sans chiffres clés : à traiter avec le [contenu des dashboards](METIER_dashboards.md).
