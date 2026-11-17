# Chantier — Dashboard, point d'entrée de la vue Statistiques

## Contexte

**Le dashboard** des fiches structure, personne, revue et éditeur (`PublicationsDashboard`) agrège les publications de l'entité par `/api/stats/pivot`, `/api/stats/collaborations` et `/api/stats/citation-points`. Ces trois points d'entrée acceptent tous les filtres de la liste des publications (`PublicationQueryFilters`).

**Ses filtres sont écrits en dur.** Seule la période figure à l'écran.
- Types : la famille « Publications ». Le graphique des types de documents fait exception : il compte toutes les familles, thèses en cours comprises, alors que la liste des publications les exclut (`excluded_doc_type=ongoing_thesis`).
- Années : de l'année en cours moins 5 à l'année en cours, parmi les années présentes (`defaultYears`).

**L'onglet Publications** de chaque fiche (`PublicationsListView`) possède le panneau des filtres, leur synchronisation avec l'URL et trois vues : Notices, Tableau, Statistiques. La vue Statistiques trace un indicateur, empilé, le long d'un axe de comparaison (l'année par défaut), sous les filtres actifs.

**Graphiques du dashboard que la vue Statistiques sait reproduire** : publications par année et par niveau d'accès (indicateur `oa_access`), types de documents (`doc_type_grouped`), classes de citation (`citation_class`). Les pays partenaires, le nuage des citations ou du FWCI et les sujets lui échappent.

## Décisions

- **Le dashboard reste un portrait fixe, sans facettes.** Un dashboard filtrable ferait double emploi avec la vue Statistiques.
- **Un graphique du dashboard ouvre son équivalent dans la vue Statistiques** de l'onglet Publications, avec les filtres du dashboard posés : ils deviennent visibles et modifiables.
- **Un graphique sans équivalent reste non cliquable**, jusqu'à l'ajout de son équivalent.

## Phasage

### 1. Graphiques déjà reproductibles

- [x] Publications par année et types de documents : lien vers la vue Statistiques, filtres du dashboard posés.
  - Le graphique des types compte les thèses en cours, la vue Statistiques les exclut : l'écart vaut leur nombre.
  - « au total » ne survivait pas à l'URL : une comparaison vide n'y était pas écrite (71a5be26).
- [x] Captures avant et après des quatre fiches.

### 2. Évaluation

- [ ] Liens depuis les chiffres clés (open access, top 10 %, collaboration internationale).
- [ ] Périmètre complet du dashboard affiché à l'écran, types compris.

### 3. Mise à jour de la documentation

- [ ] `docs/guide-utilisateur/pages-publiques/` : liens du dashboard dans `03-structures.md`, `04-personnes.md` et `05-revues-et-editeurs.md`.

## Pistes hors périmètre

- Nuage des citations ou du FWCI et sujets parmi les visualisations de la vue Statistiques.
- Statistiques dans d'autres onglets, par exemple Collaborations, pour les pays partenaires.
- Onglets Sujets et Revues dans les fiches de structure.
- Évolution annuelle d'une ventilation dans la vue Statistiques (courbes temporelles) : la comparaison impose aujourd'hui de choisir entre l'année et une autre dimension.
