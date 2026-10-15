# Chantier — Appartenance et périmètre

## Contexte

Une signature entre dans le périmètre quand `source_authorships.in_perimeter` est vrai. La phase `affiliations` le pose par deux voies : une adresse de la signature est rattachée à une structure du périmètre (`address_structures`), ou la signature contient l'identifiant d'une personne RH et le document paraît pendant son contrat (`rh_identity_signatures`). Une publication est dans le périmètre quand une de ses signatures l'est.

La table `addresses` reçoit des chaînes de natures différentes :

| Chaîne | Nature | Entrée dans `addresses` |
|---|---|---|
| Texte d'affiliation (OpenAlex, WoS, Crossref, DataCite, une partie des affiliations ScanR) | déclaration de l'auteur | adresse au sens strict |
| Nom de structure HAL, fiche de structure ScanR | entrée d'un référentiel, avec identifiant (`structId`) | nom de structure mis en adresse |
| Établissement de soutenance et laboratoires partenaires d'une thèse | propriété du document | noms posés en adresse sur toutes les signatures de la thèse |

Les noms de structures et les propriétés du document faussent les mesures faites sur les adresses : pays des adresses, signatures institutionnelles. Les adresses des thèses servent aussi au matching des personnes : elles rattachent un directeur ou un membre du jury sans IdRef.

L'identifiant d'une personne RH fait entrer une signature dans le périmètre, quel que soit son rôle. Une thèse soutenue dans un autre établissement entre donc dans le périmètre quand une personne RH fait partie du jury. Sur 2023-2026, l'extraction par identifiant de personne fait entrer ainsi 370 thèses ScanR.

Chantiers liés : `DATA_pays-des-adresses.md` et `METIER_signatures-institutionnelles.md` lisent la table `addresses` ; `DATA_collaborations-structures.md` rattache les signatures au ROR ; `DATA_alignement-auteurs.md` groupe les signatures d'un même auteur.

## Décisions

**Indices.** Le périmètre se décide à partir d'indices, posés à deux niveaux.

Au niveau de la signature :

- adresse : texte d'affiliation brut, rattaché à une structure par les formes de noms ;
- ROR de la signature ;
- structure HAL de la signature, lue dans HAL et dans les fiches de structure ScanR ;
- identité : identifiant d'une personne RH, document paru pendant son contrat.

Au niveau du document : thèse soutenue dans l'établissement, d'après le PPN de l'établissement de soutenance, parmi les `api_ids.theses` du périmètre.

La collection HAL n'est pas un indice : elle double la structure HAL.

**Structures atteintes.** Les indices bruts gardent une table par référentiel : `source_authorship_addresses`, `source_authorship_rors`, `source_authorship_hal_structures`. La vue matérialisée `source_authorship_structures` associe chaque signature aux structures du périmètre qu'elle atteint, avec l'indice (`evidence`). Le périmètre et le laboratoire se calculent sur elle.

**Indices de l'entrée.**

- Type `perimeter_evidence` : `address`, `rh_identity`, `ror`, `hal_structure`, `thesis_institution`, `thesis_partner`.
- Colonne `perimeter_evidence` (tableau) sur `source_authorships`, `authorships` et `publications`. `authorships` réunit les indices de ses signatures. `publications` réunit ceux des signatures de personnes non exclues, et les indices propres au document.
- `in_perimeter` est une colonne générée, vraie quand `perimeter_evidence` est non vide.
- Une seule requête SQL calcule les indices d'une signature. Elle sert à la phase `affiliations` et au recalcul en tâche de fond après une correction d'adresse dans l'administration.

**Publication.** Une publication est dans le périmètre par les indices de ses auteurs, ou par un indice propre au document. Les autres rôles (direction de thèse, jury, édition, traduction) comptent pour la personne seulement. La structure HAL suffit. Une publication appartient à une structure par ses auteurs (`publication_structures`).

**Corrections, indice par indice.** Aucune table de rejet propre au périmètre :

- identité RH : le rejet de la signature (`rejected_authorships`) coupe le lien à la personne ;
- adresse : le lien adresse → structure s'infirme dans `address_structures`, pour toutes les signatures de cette adresse ;
- ROR : un ROR du périmètre posé sur une adresse sans structure du périmètre est écarté ;
- structure HAL : une erreur du dépôt se corrige dans HAL ; une erreur de correspondance se corrige dans `ref.hal_structures.structure_id` ;
- thèse soutenue dans l'établissement : jamais écartée, theses.fr fait autorité.

**Référentiel des structures HAL.**

- `ref.hal_structures` : identifiant, nom, sigle, type, pays, statut (`VALID`, `OLD`, `INCOMING`), ROR, dates ;
- `ref.hal_structure_relations` : parent, enfant, d'après `parentDocid_i` ;
- `ref.hal_structure_aliases` : alias, structure conservée, d'après `aliasDocid_i`. Un alias est une fiche en double, fondue dans la structure conservée.

Un nœud en tête de la phase `affiliations` charge depuis l'API `ref/structure` les structures citées et absentes du référentiel, puis leurs parents.

**Structure HAL d'une signature.** `source_authorship_hal_structures` garde les structures directes de la signature : `affiliation/@ref` de l'auteur dans le TEI de HAL, `structId` d'une affiliation ScanR.

**Correspondance avec les structures internes.** Une structure HAL rejoint une structure interne par son ROR, ou par sa colonne `structure_id`, clé étrangère vers `structures`. Sans correspondance, la branche `hal_structure` de la vue remonte les parents HAL jusqu'à la première structure qui en a une. HAL ne relie pas les fiches successives d'un laboratoire : le ROR partagé en relie une partie, `structure_id` relie les autres.

**Table `addresses` réservée aux textes d'affiliation.** Les noms de structures HAL et ScanR et les noms des thèses quittent `addresses`, une fois leurs voies d'entrée en place et mesurées.

**Structures d'une thèse.** La notice theses.fr garde le PPN IdRef de l'établissement de soutenance et de chaque laboratoire partenaire. La vue `source_authorship_structures` a deux branches de thèse :

- l'établissement de soutenance, reconnu par son PPN dans `api_ids.theses`, rattache toutes les signatures de la thèse (indice `thesis_institution`) ;
- un laboratoire partenaire, reconnu par son PPN dans `idref_structures`, rattache la signature du doctorant (indice `thesis_partner`).

`idref_structures` (PPN, structure, forme de nom, confirmation) suit le modèle de `address_structures`. La phase `affiliations` résout par les formes de noms le nom de chaque partenaire. L'administration confirme ou infirme un rattachement, une fois par PPN. `api_ids.theses` reste la liste des établissements que le moissonnage interroge.

**Thèses soutenues ailleurs.** Une thèse entrée par un membre du jury ou un directeur est créée hors du périmètre. Elle figure dans l'onglet Thèses de la page de la personne. Elle est absente des listes de publications et des onglets Thèses de l'université et des laboratoires.

## Phasage

### Phase 1 — Indices de l'entrée

- [x] Requête SQL unique des indices d'une signature, pour le calcul complet et le recalcul après une correction d'adresse.
- [x] Colonne `evidence` de `source_authorship_structures`, valeur `address` pour la branche existante.
- [x] Indices de l'entrée sur les signatures, les authorships et les publications, pour les voies existantes (adresse, identité). Sur la base de production, le remplissage de la migration redonne exactement le périmètre en place.

### Phase 2 — Référentiels

- [x] Référentiel `ref.hal_structures` et nœud de chargement.
- [x] Table `source_authorship_hal_structures`, lue dans HAL et dans les fiches de structure ScanR. Quand aucune affiliation ScanR n'est marquée laboratoire, les `structId` comprennent les tutelles : la branche `hal_structure` garde les structures les plus basses de la hiérarchie.
- [x] Branches `hal_structure` et `ror` de `source_authorship_structures`.
- [x] Mesure : signatures qui entrent par une structure HAL ou un ROR et pas par une adresse, et réciproquement. ROR, mesure du 2026-10-15 sur le périmètre des personnes : 3 725 signatures entrent par le ROR seul. La règle de l'adresse écarte 18 132 ROR du périmètre, à 90 % d'OpenAlex : des ROR erronés (« Laboratoire de Mathématiques de Versailles » avec le ROR du LMBP), et des adresses trop courtes pour la résolution (« Territoires », « Unité de Nutrition Humaine »). Structure HAL : aucune signature n'entre par la structure HAL seule, car l'adresse HAL est le nom de la même structure. 5 671 signatures HAL entrent par l'adresse et pas par la structure HAL : leurs fiches HAL d'avant 2017, sans ROR (UBP, SIGMA Clermont, anciennes fiches des laboratoires), sont sans correspondance interne.
- [x] Structure interne (`structure_id`) des fiches HAL sans ROR connu, d'après les noms que la résolution des adresses rattache déjà aux structures internes : 214 fiches pour 37 structures (`interfaces/cli/oneshot/match_hal_structures.py`). Restent 1 359 signatures HAL qui entrent par l'adresse et pas par la structure HAL, dont 1 261 sans structure HAL dans le TEI.
- [x] Migration des branches de la vue appliquée, pipeline relancé depuis `affiliations`. Signatures du périmètre : 499 229 (+3 689). Authorships : 184 031 (+2 148), la plupart sur des publications déjà dans le périmètre. Publications : 75 219 (+34), dont 46 entrées par le seul ROR.

### Phase 3 — Indices propres au document

- [x] Thèse soutenue dans l'établissement : PPN de l'établissement de soutenance dans `meta` de la notice theses.fr, indice `thesis_institution` (2 597 publications).
- [x] Thèses soutenues ailleurs, créées hors du périmètre : les indices d'une publication viennent de ses seuls auteurs. L'onglet Thèses de la page d'une personne liste les thèses par leur type, quelle que soit leur source.
- [x] Mesure : 75 219 publications du périmètre avant, 73 511 après. Sortent 1 580 thèses soutenues ailleurs (rapporteur, jury, présidence ou direction à l'UCA), 56 ouvrages dirigés et 73 documents sans auteur de l'UCA. Aucune thèse soutenue à l'UCA ne sort.

### Phase 4 — Adresses au sens strict

- [x] Signal de remplacement des adresses de thèse : branches de thèse de `source_authorship_structures`, par le PPN de l'établissement et des laboratoires partenaires. Simulation sur 2 642 thèses : 2 508 gardent les mêmes laboratoires, 67 en gagnent, 67 en perdent faute de PPN du partenaire.
- [x] Normalisation : noms de structures HAL et ScanR et noms des thèses hors de `addresses`. Les structures HAL et leurs ROR sont lus dans le TEI. Une affiliation ScanR avec `structId` est une fiche de structure HAL : elle donne une structure HAL et son ROR à la signature, sans adresse.
- [ ] Reprise du stock : réhydratation de `staging` depuis le raw store, `normalize` complet.

### Phase 5 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- **Scission d'un laboratoire.** L'ancienne fiche HAL se rattache à un seul des laboratoires issus de la scission, ou à aucun : ses signatures remontent alors à l'université seule.
- **Signature hors périmètre.** La personne est bien attribuée, mais une source lui prête une fausse affiliation. Une décision durable (notice, personne), sur le modèle de `rejected_authorships`, écarterait les indices de niveau signature pour cette personne sur cette notice. À trancher selon la fréquence du cas dans l'administration.
- **Laboratoire d'une signature entrée par l'identité.** Une signature entrée dans le périmètre par l'identifiant d'une personne RH reste sans laboratoire. Piste : le déduire des publications de la personne.
- **Consolidation.** Par paire (publication, personne), comme `authorships`, ou par auteur aligné (`DATA_alignement-auteurs.md`). La seconde rend le périmètre d'une publication indépendant du matching des personnes.
- **Membres d'un laboratoire multisite sur un autre site.** Une forme de nom sans contexte rattache au laboratoire les adresses de ses autres sites. Mesure du 2026-10-15, signatures dont l'adresse cite un autre site sans citer Clermont ni l'UCA : IHRIM 4 223 sur 16 593 (Lyon, ENS de Lyon), LIMOS 452 (Mines Saint-Étienne), LMV 235 (Saint-Étienne, Lyon), GEOLAB 226 (Limoges). Piste : formes de noms des autres sites sur ces quatre laboratoires, et marque `other_site` sur le lien adresse → laboratoire, avant de décider d'exclure.
- **Correction des correspondances HAL.** Une erreur de correspondance d'une structure HAL se corrige dans `ref.hal_structures.structure_id`, sans interface d'administration. A construire si les cas apparaissent dans l'administration.
- **Partenaires de thèse sans PPN.** theses.fr ne donne pas le PPN de 301 mentions de partenaires (85 noms), surtout dans les thèses en cours : la thèse reste sans laboratoire jusqu'à ce que la notice le donne. Piste : les reconnaître aussi par leur nom, sans décision durable de l'administration faute de PPN pour clé.
