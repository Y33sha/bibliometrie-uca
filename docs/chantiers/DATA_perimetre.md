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

**Indices bruts et structures atteintes.** Les indices bruts gardent une table par référentiel : `source_authorship_addresses`, `source_authorship_rors`, `source_authorship_hal_structures`. La vue matérialisée `source_authorship_structures` associe chaque signature aux structures du périmètre qu'elle atteint. Elle gagne une colonne `evidence` (`address`, `ror`, `hal_structure`), et une branche de requête par indice. Les corrections vivent dans les tables sources, donc la vue reste une vue matérialisée. Son index unique, qu'exige le rafraîchissement concurrent, inclut `evidence`. Le périmètre et le laboratoire se calculent sur elle.

**Indices de l'entrée.** Une signature et une publication entrent dans le périmètre par un ou plusieurs indices : une signature OpenAlex peut entrer à la fois par son adresse, son ROR et l'identité RH. Les indices enregistrés rendent mesurable l'apport de chaque voie.

- Type `perimeter_evidence` : `address`, `rh_identity`, puis `ror`, `hal_structure` et `thesis_institution` avec leur phase. La colonne `evidence` de `source_authorship_structures` prend ses valeurs de structure.
- Colonne `perimeter_evidence` (tableau) sur `source_authorships`, `authorships` et `publications`, recalculée à chaque run. `authorships` réunit les indices de ses signatures. `publications` réunit ceux des signatures de personnes non exclues, et les indices propres au document.
- `in_perimeter` est une colonne générée, vraie quand `perimeter_evidence` est non vide.
- Une seule requête SQL calcule les indices d'une signature, sur la vue `source_authorship_structures`. Elle sert au calcul complet de la phase `affiliations` et au recalcul après une correction d'adresse dans l'administration. Ce recalcul s'exécute en tâche de fond : il rafraîchit la vue, puis recalcule les signatures, les authorships et les publications touchées.

**Publication.** Une publication est dans le périmètre si une de ses signatures l'est, ou par un indice propre au document. La structure HAL suffit : elle couvre les années antérieures au premier export RH, les documents présents seulement dans HAL, et les adresses qui citent un CHU sans l'université.

**Corrections, indice par indice.** Aucune table de rejet propre au périmètre :

- identité RH : le rejet de la signature (`rejected_authorships`) coupe le lien à la personne ;
- adresse : le lien adresse → structure s'infirme dans `address_structures`, pour toutes les signatures de cette adresse ;
- ROR : une règle, à confirmer par la mesure de la phase 2. Un ROR du périmètre sur une adresse hors du périmètre est écarté ;
- structure HAL : une erreur du dépôt se corrige dans HAL ; une erreur de correspondance entre structure HAL et structure interne se corrige dans le référentiel ;
- thèse soutenue dans l'établissement : jamais écartée, theses.fr fait autorité.

**Référentiel des structures HAL.** Sur le modèle du ROR :

- `ref.hal_structures` : identifiant, nom, sigle, type, pays, statut (`VALID`, `OLD`, `INCOMING`), ROR ;
- `ref.hal_structure_relations` : parent, enfant, d'après `parentDocid_i` ;
- `ref.hal_structure_aliases` : alias, structure conservée, d'après `aliasDocid_i`. Un alias est une fiche en double, fondue dans la structure conservée et absente de l'API.

HAL ne publie pas de dump. Un nœud en tête de la phase `affiliations` interroge l'API `ref/structure` par lots d'identifiants : les structures citées par les notices et absentes du référentiel, puis leurs parents. En mode `full`, il relit tout le référentiel. Le pays d'une structure HAL est un candidat `hal_structure` du chantier des pays des adresses.

**Structure HAL d'une signature.** `source_authorship_hal_structures` garde les structures directes de la signature : la référence `affiliation/@ref` de l'auteur dans le TEI de HAL, le `structId` d'une affiliation ScanR. Les tutelles se lisent dans le référentiel.

**Correspondance avec les structures internes.** Une structure HAL rejoint une structure interne par son ROR, ou par la liste de `structId` de `structures.api_ids->'hal'`. Sans correspondance, la branche `hal_structure` de la vue remonte les parents HAL jusqu'à la première structure qui en a une.

HAL ne relie pas les structures successives d'un laboratoire. Chaque période a sa fiche, avec ses dates ; l'ancienne passe à `OLD`. Le ROR partagé relie une partie des fiches ; la liste de `api_ids` relie les autres.

**Table `addresses` réservée aux textes d'affiliation.** Les noms de structures HAL et ScanR et les noms des thèses quittent `addresses`, une fois leurs voies d'entrée en place et mesurées.

**Thèses soutenues ailleurs.** Une thèse entrée par un membre du jury est créée hors du périmètre. Elle figure dans l'onglet Thèses de la page de la personne. Elle est absente des listes de publications et des onglets Thèses de l'université et des laboratoires.

## Phasage

### Phase 1 — Indices de l'entrée

- [x] Requête SQL unique des indices d'une signature, pour le calcul complet et le recalcul après une correction d'adresse.
- [x] Colonne `evidence` de `source_authorship_structures`, valeur `address` pour la branche existante.
- [x] Indices de l'entrée sur les signatures, les authorships et les publications, pour les voies existantes (adresse, identité). Sur la base de production, le remplissage de la migration redonne exactement le périmètre en place.

### Phase 2 — Référentiels

- [x] Référentiel `ref.hal_structures` et nœud de chargement.
- [x] Table `source_authorship_hal_structures`, lue dans HAL et dans les fiches de structure ScanR. Quand aucune affiliation ScanR n'est marquée laboratoire, les `structId` comprennent les tutelles : la branche `hal_structure` garde les structures les plus basses de la hiérarchie.
- [x] Branches `hal_structure` et `ror` de `source_authorship_structures`.
- [ ] Mesure : signatures qui entrent par une structure HAL ou un ROR et pas par une adresse, et réciproquement. ROR, mesure du 2026-10-15 sur le périmètre des personnes : 3 725 signatures entrent par le ROR seul. La règle de l'adresse écarte 18 132 ROR du périmètre, à 90 % d'OpenAlex : des ROR erronés (« Laboratoire de Mathématiques de Versailles » avec le ROR du LMBP), et des adresses trop courtes pour la résolution (« Territoires », « Unité de Nutrition Humaine »).

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

- **Scission d'un laboratoire.** L'ancienne fiche HAL peut figurer dans les `api_ids` des deux structures issues de la scission : ses signatures atteignent les deux laboratoires, et le décompte par laboratoire compte double. Sans correspondance, la remontée des parents rattache ses signatures à l'université seule. À trancher cas par cas.
- **Signature hors périmètre.** La personne est bien attribuée, mais une source lui prête une fausse affiliation, souvent juste pour un coauteur. Une décision durable (notice, personne), sur le modèle de `rejected_authorships`, écarterait tous les indices de niveau signature pour cette personne sur cette notice. Elle complète l'exclusion d'une personne (`persons.exclusion = 'out_of_perimeter'`), qui vaut pour toutes ses publications, futures comprises. À trancher selon la fréquence du cas dans l'administration.
- **Laboratoire d'une signature entrée par l'identité.** Une signature entrée dans le périmètre par l'identifiant d'une personne RH reste sans laboratoire. Piste : le déduire des publications de la personne. Les `department_name` de l'export RH désignent rarement un laboratoire.
- **Consolidation.** Par paire (publication, personne), comme `authorships`, ou par auteur aligné (`DATA_alignement-auteurs.md`). La seconde rend le périmètre d'une publication indépendant du matching des personnes.
