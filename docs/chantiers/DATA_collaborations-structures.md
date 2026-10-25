# Chantier — Collaborations entre structures

## Contexte

Une analyse de réseau des collaborations demande de rattacher chaque contribution source à ses structures, y compris hors du périmètre. La table `structures` contient seulement les structures du périmètre et leurs tutelles. La phase `affiliations` les reconnaît dans les adresses grâce à des formes de noms saisies à la main. Ce procédé est infaisable pour toutes les structures mondiales.

Les sources fournissent des ROR par contribution source. Couverture mesurée dans le raw store, sur un échantillon de 3 000 enregistrements par source sauf OpenAlex et Crossref (raw store entier) :

| Source | Champ | Contributions sources avec ROR |
|---|---|---|
| OpenAlex | `authorships[].institutions[].ror` | 588 institutions sans ROR sur 5 872 380 |
| WoS | `address_spec.organizations.organization[].ror_id` | 98 % |
| Crossref | `author[].affiliation[].id` (`id-type` ROR) | 13 % |
| ScanR | `authors[].affiliations[].ror` | 21 % |
| HAL | `<idno type="ROR">` des structures du TEI (`label_xml`) | non mesuré |
| DataCite | `creators[].affiliation[].affiliationIdentifier` | 0 % : rendu par l'API avec le paramètre `affiliation=true` seulement |

La normalisation garde seulement le texte des affiliations, dans `addresses`.

Types des institutions OpenAlex : `education` 54 %, `facility` 32 %, `government` 9 %, `healthcare` 4 %. Les nœuds du réseau sont donc des établissements et des laboratoires.

Les relations parent/enfant du ROR coïncident avec `structure_parents` sur le périmètre, à quelques écarts près (dump ROR v2.14).

## Décisions

**Deux référentiels.** `structures` et `structure_parents` restent le référentiel interne : elles définissent le périmètre et servent à la phase `affiliations`. Une partie des tutelles concerne des structures internes absentes du ROR. Le ROR est un référentiel externe en lecture seule, chargé depuis le dump publié sur Zenodo. `structures.ror_id` relie les deux, avec une contrainte d'unicité.

```
ror_organizations
  ror_id         PRIMARY KEY
  name
  country_code
  types          ror_type[]
  status

ror_relations
  parent_ror_id  → ror_organizations
  child_ror_id   → ror_organizations
  PRIMARY KEY (parent_ror_id, child_ror_id)
```

**Rafraîchissement du référentiel par le pipeline.** En tête de la phase `affiliations`, le pipeline compare le nom de la dernière archive publiée sur Zenodo au nom de la dernière archive importée. Il télécharge et importe seulement une version plus récente. La table `ror_dump_imports (version, imported_at)` garde une ligne par import.

**ROR des sources par contribution source.** La phase `normalize` remplit la table de liens `source_contribution_rors (source_contribution_id, ror_id, address_id)`. `address_id` désigne l'adresse dont l'affiliation porte le ROR ; il est vide pour un ROR donné sans texte d'affiliation. Ces liens entrent dans `content_hash`. `ror_id` est sans clé étrangère vers `ror_organizations` : une source peut citer un ROR plus récent que le dump importé, et l'import remplace tout le référentiel.

Lecture par source :

- OpenAlex : ROR des institutions de la contribution source.
- WoS : ROR des organisations des adresses de l'auteur.
- Crossref : identifiants ROR des affiliations.
- ScanR : ROR de toutes les affiliations de l'auteur, tutelles comprises.
- HAL : ROR des structures du TEI auxquelles l'auteur est affilié.
- DataCite : `affiliationIdentifier` de schéma ROR. Les trois adaptateurs qui interrogent `/dois` (extraction, `fetch_missing`, `fetch_stale`) partagent le paramètre `affiliation=true`.

**ROR par publication.** La vue matérialisée `publication_rors (publication_id, ror_id, cited)` réunit les ROR de tous les auteurs d'une publication, périmètre compris : ceux que donnent les sources pour les contributions sources alignées, et ceux des structures que la phase `affiliations` reconnaît (`publication_structures`). Les contributions sans personne en sont ; celles d'une personne qui n'en est pas une (`not_a_person`) en sont exclues. Chaque ROR entre avec ses ancêtres de `ror_relations` : un établissement compte aussi les publications de ses laboratoires, et la lecture reste une jointure simple. `cited` distingue les ROR cités des ancêtres ajoutés. Distinguer les coauteurs relèverait d'une vue par contribution, hors de ce chantier.

**Affichage.** Les organisations partenaires sont listées telles quelles, laboratoires et établissements mêlés. Le lecteur filtre par type, par pays et par période.

**Cohérence des référentiels.** Un rapport compare `structure_parents` à `ror_relations` dans les deux sens, par clôture transitive. Un parent ROR est couvert s'il est un ancêtre dans `structure_parents`. Une tutelle est couverte si son parent est un ancêtre dans le ROR. Chaque écart se corrige dans `structure_parents` ou se signale au ROR.

## Phasage

### 1. Référentiel ROR

- [x] Migration : tables `ror_organizations` et `ror_relations`.
- [x] Script de chargement du dump ROR : `interfaces/cli/imports/import_ror_dump.py`.
- [x] Rapport de cohérence entre `structure_parents` et `ror_relations` : `interfaces/cli/maintenance/report_ror_coherence.py`.
- [x] Contrainte d'unicité sur `structures.ror_id`.

### 2. ROR des sources

- [x] DataCite : paramètre `affiliation=true` partagé par les trois adaptateurs.
- [x] Migration : tables `source_contribution_rors` et `ror_dump_imports`.
- [x] Writer partagé : ROR des contributions sources, dans `content_hash`.
- [x] Normalisation OpenAlex, WoS, Crossref, ScanR, HAL et DataCite : lecture des ROR.
- [x] Rafraîchissement du référentiel ROR en tête de la phase `affiliations`.
- [x] Reprise de l'existant : réextraction DataCite, réhydratation de `staging` depuis le raw store, `normalize` complet.
- [x] Couverture par source, 2026-10-16 : part des contributions sources avec au moins un ROR. WoS 46 %, OpenAlex 40 %, ScanR 20 %, Crossref 13 %, HAL 9 %, DataCite 0,2 %.

### 3. Vue consolidée

- [x] Vue matérialisée `publication_rors`, avec les ancêtres des ROR cités, rafraîchie par la phase `finalize`. Base locale : 1 171 033 lignes, dont 828 037 ROR cités, sur 75 436 publications ; 87 s de calcul.
- [x] Tests : ancêtres ajoutés, contributions sans personne comprises, fausses entités écartées.

### 4. Interface

- [ ] Onglet « Collaborations » de la page d'une structure : organisations partenaires classées par nombre de copublications, filtrables par période, pays et type d'organisation, avec le lien vers les copublications.
- [ ] Facette « Organisation partenaire » dans la recherche de publications.
- [ ] Dimension « partenaire » dans le pivot des statistiques.
- [ ] Export du réseau (CSV, GEXF) pour Gephi ou VOSviewer.

### 5. Mise à jour de la documentation

- [ ] `docs/` : référentiel ROR, table de liens, vue consolidée.

## Questions ouvertes

- Faux positifs des sources hors périmètre : accord de deux sources ; vérification par un service externe (ISTEX…) dans un chantier distinct.
