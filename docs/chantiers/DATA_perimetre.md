# Chantier — Périmètre

## Contexte

Une signature entre dans le périmètre quand `source_authorships.in_perimeter` est vrai. La phase `affiliations` le pose par deux voies : une adresse de la signature est rattachée à une structure du périmètre (`address_structures`), ou la signature contient l'identifiant d'une personne RH et le document paraît pendant son contrat (`rh_identity_signatures`).

Les marqueurs d'appartenance sont de natures différentes :

| Marqueur | Nature | Voie d'entrée |
|---|---|---|
| Texte d'affiliation (OpenAlex, WoS, Crossref, DataCite, une partie des affiliations ScanR) | déclaration de l'auteur | adresse |
| Nom de structure HAL, fiche de structure ScanR | rattachement à un référentiel, avec identifiant (`structId`) | nom de structure mis en adresse |
| Établissement de soutenance et laboratoires partenaires d'une thèse | propriété du document | noms posés en adresse sur toutes les signatures de la thèse |
| Personne RH pendant son contrat | identité de la personne | identifiant de la signature |
| ROR d'une signature (`source_authorship_rors`) | rattachement à un référentiel, avec identifiant | aucune |

Seul le texte d'affiliation est une adresse au sens strict. Les noms de structures et les propriétés du document empruntent l'adresse, seule voie d'entrée avant la règle RH.

Les adresses des thèses servent aussi au matching des personnes : elles rattachent un directeur ou un membre du jury sans IdRef.

Les adresses HAL viennent de `authIdHasStructure_fs`, qui donne chaque structure de l'auteur, tutelles comprises, chacune en adresse distincte. `parse_author_structures` préfère `authIdHasPrimaryStructure_fs`, qui donne les seules structures primaires, mais ce champ est absent de `HAL_FIELDS`, donc des payloads moissonnés. Une tutelle reconnue rattache la signature au périmètre quand le nom de son laboratoire est inconnu de la résolution des affiliations.

## Questions ouvertes

- **Raison de l'entrée dans le périmètre** (affiliation, personne RH dans ses dates) : enum à ajouter, puis suppression éventuelle du booléen.
- **Affiliations HAL.** Une publication présente seulement dans HAL entre dans le périmètre par ses noms de structures. Première voie : marquer l'origine (texte brut ou nom de structure) sur le lien entre signature et adresse, car une même adresse peut venir des deux. Seconde voie : relier la signature à sa structure HAL par son identifiant, sur le modèle de `source_authorship_rors`. Un référentiel des structures HAL donne alors leurs parents, leur ROR et leur pays.
- **Référentiel des structures HAL (proposition).** Sur le modèle du ROR : `ref.hal_structures` (identifiant, nom, sigle, type, pays, validité) et `ref.hal_structure_relations` (parent, enfant). L'API `ref/structure` de HAL donne `country_s`, `type_s`, `valid_s`, `parentDocid_i` et `aliasDocid_i`. `aliasDocid_i` liste les structures fusionnées dans une structure : le chargement résout un alias vers la structure conservée. HAL ne publie pas de dump. Un nœud en tête de la phase `affiliations` interroge l'API par lots d'identifiants, pour les seules structures citées par les notices et absentes du référentiel. Le lien `source_authorship_hal_structures (source_authorship_id, hal_structure_id, address_id)` suit `source_authorship_rors`. Le pays d'une structure est alors un candidat `hal_structure` du chantier des pays des adresses.
- **Structures primaires HAL.** Garder seulement les structures primaires réduit le nombre d'adresses, mais une signature dont le laboratoire primaire est inconnu sort alors du périmètre. Mesure à faire sur un échantillon de notices, les deux champs demandés à l'API : nombre de signatures dont seule une tutelle est reconnue.
- **Affiliations ScanR.** `authors[].affiliations` mêle des textes bruts (sans `structId`) et des fiches de structure HAL (`structId`, `hal_docid`), dont le `name` met bout à bout nom, sigles, tutelles et adresse postale. `select_leaf_affiliations` garde seulement l'affiliation marquée `id_name_author_labo` quand l'auteur en a une, et écarte les autres textes bruts de l'auteur.
- **Thèses.** Une thèse soutenue dans l'établissement relève du périmètre en tant que document, avec toutes ses signatures. Faut-il une voie d'entrée par le document, distincte de l'adresse ? Les adresses du document resteraient alors un signal du matching des personnes, marqué comme tel.
- **Thèses soutenues ailleurs.** La règle RH ignore le rôle de la signature. Une thèse soutenue dans un autre établissement entre donc dans le périmètre quand une personne RH fait partie du jury. Sur 2023-2026, l'extraction par identifiant de personne fait entrer 370 thèses ScanR, le plus souvent par un membre du jury. Piste : une publication hors périmètre, présente dans l'onglet Thèses de la page de la personne, absente des listes de publications et des onglets Thèses de l'université et des laboratoires.
