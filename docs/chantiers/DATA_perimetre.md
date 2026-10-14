# Chantier — Appartenance et périmètre

## Contexte

Une signature entre dans le périmètre quand `source_authorships.in_perimeter` est vrai. La phase `affiliations` le pose par deux voies : une adresse de la signature est rattachée à une structure du périmètre (`address_structures`), ou la signature contient l'identifiant d'une personne RH et le document paraît pendant son contrat (`rh_identity_signatures`). Une publication est dans le périmètre quand une de ses signatures l'est.

La table `addresses` reçoit des chaînes de natures différentes :

| Chaîne | Nature | Entrée dans `addresses` |
|---|---|---|
| Texte d'affiliation (OpenAlex, WoS, Crossref, DataCite, une partie des affiliations ScanR) | déclaration de l'auteur | adresse au sens strict |
| Nom de structure HAL, fiche de structure ScanR | entrée d'un référentiel, avec identifiant (`structId`) | nom de structure mis en adresse |
| Établissement de soutenance et laboratoires partenaires d'une thèse | propriété du document | noms posés en adresse sur toutes les signatures de la thèse |

Les noms de structures et les propriétés du document empruntent l'adresse, seule voie d'entrée avant la règle RH. Ils faussent les mesures faites sur les adresses : pays des adresses, signatures institutionnelles.

Le ROR d'une signature (`source_authorship_rors`) reste sans voie d'entrée. Une collection HAL agrège automatiquement les notices de ses structures : elle découle de la structure HAL des auteurs. Quand une structure HAL change de nom ou de statut, HAL en crée une nouvelle, qui remplace l'ancienne ; la collection, elle, reste.

Les adresses HAL viennent de `authIdHasStructure_fs`, qui donne chaque structure de l'auteur, tutelles comprises, avec son identifiant. `parse_author_structures` préfère `authIdHasPrimaryStructure_fs`, qui donne les seules structures primaires, mais ce champ est absent de `HAL_FIELDS`, donc des payloads moissonnés. Une tutelle reconnue rattache la signature au périmètre quand le nom de son laboratoire est inconnu de la résolution des affiliations.

`authors[].affiliations` de ScanR mêle des textes bruts (sans `structId`) et des fiches de structure HAL (`structId`, `hal_docid`), dont le `name` met bout à bout nom, sigles, tutelles et adresse postale. `select_leaf_affiliations` garde seulement l'affiliation marquée `id_name_author_labo` quand l'auteur en a une, et écarte les autres textes bruts de l'auteur.

Les adresses des thèses servent aussi au matching des personnes : elles rattachent un directeur ou un membre du jury sans IdRef.

L'identifiant d'une personne RH fait entrer une signature dans le périmètre, quel que soit le rôle de la personne : auteur, directeur de thèse, rapporteur ou membre du jury. Une thèse soutenue dans un autre établissement entre donc dans le périmètre quand une personne RH fait partie du jury. Sur 2023-2026, l'extraction par identifiant de personne fait entrer ainsi 370 thèses ScanR, le plus souvent par un membre du jury.

Chantiers liés : `DATA_pays-des-adresses.md` et `METIER_signatures-institutionnelles.md` lisent la table `addresses` ; `DATA_collaborations-structures.md` rattache les signatures au ROR ; `DATA_alignement-auteurs.md` groupe les signatures d'un même auteur.

## Décisions

**Indices et décision.** Le périmètre se décide à partir d'indices, posés à deux niveaux.

Au niveau de la signature :

- adresse : texte d'affiliation brut, rattaché à une structure par les formes de noms ;
- ROR de la signature ;
- structure HAL de la signature, lue dans HAL et dans les fiches de structure ScanR ;
- identité : identifiant d'une personne RH, document paru pendant son contrat.

Au niveau du document : thèse soutenue dans l'établissement, d'après le PPN de l'établissement de soutenance, parmi les `api_ids.theses` du périmètre.

La collection HAL n'est pas un indice : elle découle de la structure HAL, qui désigne en plus l'auteur et son laboratoire.

**Deux étages de tables.** Les indices bruts gardent une table par référentiel : `source_authorship_addresses`, `source_authorship_rors`, `source_authorship_hal_structures`. Une table résolue réunit les structures du référentiel interne atteintes par chaque signature. La phase `affiliations` la remplit ; le périmètre et le laboratoire se calculent sur elle.

```
source_authorship_structures
  source_authorship_id  → source_authorships
  structure_id          → structures
  method                address | ror | hal_structure
  address_id            → addresses, vide hors méthode address
```

**Raisons de l'entrée.** Une signature et une publication entrent dans le périmètre par une ou plusieurs raisons : une signature OpenAlex peut entrer à la fois par son adresse, son ROR et l'identité RH. Les raisons rendent mesurable l'apport de chaque voie. Proposition à confirmer : une colonne `perimeter_reasons` (tableau d'une énumération) sur `source_authorships` et sur `publications`, recalculée à chaque run ; un tableau vide vaut hors du périmètre.

**Publication.** Une publication est dans le périmètre si une de ses signatures l'est, ou par une raison propre au document. La structure HAL suffit : elle couvre les années antérieures au premier export RH, les documents présents seulement dans HAL, et les adresses qui citent un CHU sans l'université.

**Corrections, indice par indice.** Aucune table de rejet propre au périmètre :

- identité RH : le rejet de la signature (`rejected_authorships`) coupe le lien à la personne ;
- adresse : le lien adresse → structure s'infirme dans `address_structures`, pour toutes les signatures de cette adresse ;
- ROR : une règle, à confirmer par la mesure de la phase 2. Un ROR du périmètre sur une adresse hors du périmètre est écarté ;
- structure HAL : une erreur du dépôt se corrige dans HAL ; une erreur de correspondance entre structure HAL et structure interne se corrige dans le référentiel ;
- thèse soutenue dans l'établissement : jamais écartée, theses.fr fait autorité.

**Référentiel des structures HAL.** Sur le modèle du ROR : `ref.hal_structures` (identifiant, nom, sigle, type, pays, validité, ROR) et `ref.hal_structure_relations` (parent, enfant). L'API `ref/structure` de HAL donne `country_s`, `type_s`, `valid_s`, `parentDocid_i`, `aliasDocid_i` et `ror_s`. `aliasDocid_i` liste les structures fusionnées dans une structure : le chargement résout un alias vers la structure conservée. HAL ne publie pas de dump. Un nœud en tête de la phase `affiliations` interroge l'API par lots d'identifiants, pour les seules structures citées par les notices et absentes du référentiel. Une structure HAL rejoint une structure interne par son ROR. Le pays d'une structure HAL est un candidat `hal_structure` du chantier des pays des adresses.

**Table `addresses` réservée aux textes d'affiliation.** Les noms de structures HAL et ScanR et les noms des thèses quittent `addresses`, une fois leurs voies d'entrée en place et mesurées.

**Thèses soutenues ailleurs.** Une thèse entrée par un membre du jury est créée hors du périmètre. Elle figure dans l'onglet Thèses de la page de la personne. Elle est absente des listes de publications et des onglets Thèses de l'université et des laboratoires.

## Phasage

### Phase 1 — Raisons de l'entrée

- [ ] Raisons de l'entrée, plusieurs par signature et par publication, posées par la phase `affiliations` pour les voies existantes (adresse, identité). Le périmètre reste inchangé.
- [ ] Table `source_authorship_structures`, remplie depuis les adresses.

### Phase 2 — Référentiels

- [ ] Référentiel `ref.hal_structures` et nœud de chargement.
- [ ] Table `source_authorship_hal_structures`, lue dans HAL et dans les fiches de structure ScanR.
- [ ] Méthodes `hal_structure` et `ror` dans `source_authorship_structures`.
- [ ] Mesure : signatures qui entrent par une structure HAL ou un ROR et pas par une adresse, et réciproquement.

### Phase 3 — Raisons propres au document

- [ ] Thèse soutenue dans l'établissement.
- [ ] Thèses soutenues ailleurs, créées hors du périmètre.
- [ ] Mesure : publications gagnées et perdues.

### Phase 4 — Adresses au sens strict

- [ ] Signal de remplacement des adresses de thèse pour le matching des personnes.
- [ ] Normalisation : noms de structures HAL et ScanR et noms des thèses hors de `addresses`.
- [ ] Reprise du stock : réhydratation de `staging` depuis le raw store, `normalize` complet.

### Phase 5 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- **Booléen `in_perimeter`.** Les raisons le rendent-elles superflu ?
- **Correspondance des structures HAL renommées.** Une structure interne doit rejoindre toutes les structures HAL qui se sont succédé sous son nom. Le ROR en relie une partie (`ref/structure` rend les structures valides et anciennes d'un même ROR). Les notices de la collection du laboratoire relient les autres.
- **Signature hors périmètre.** La personne est bien attribuée, mais une source lui prête une fausse affiliation, souvent juste pour un coauteur. Une décision durable (notice, personne), sur le modèle de `rejected_authorships`, écarterait toutes les raisons de niveau signature pour cette personne sur cette notice. Elle complète l'exclusion d'une personne (`persons.exclusion = 'out_of_perimeter'`), qui vaut pour toutes ses publications, futures comprises. À trancher selon la fréquence du cas dans l'administration.
- **Structures primaires HAL.** Garder seulement les structures primaires réduit le nombre de structures par signature, mais une signature dont le laboratoire primaire est inconnu sort alors du périmètre. Mesure à faire sur un échantillon de notices, les deux champs demandés à l'API : nombre de signatures dont seule une tutelle est reconnue.
- **Laboratoire d'une signature entrée par l'identité.** Une signature entrée dans le périmètre par l'identifiant d'une personne RH reste sans laboratoire. Piste : le déduire des publications de la personne. Les `department_name` de l'export RH désignent rarement un laboratoire.
- **Consolidation.** Par paire (publication, personne), comme `authorships`, ou par auteur aligné (`DATA_alignement-auteurs.md`). La seconde rend le périmètre d'une publication indépendant du matching des personnes.
