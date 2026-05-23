# Glossaire métier

*A compléter*

## Adresse {#adresse}
Chaîne de caractères associée à une publication et signalant l'affiliation institutionnelle de chaque auteur. Fournie par chaque auteur à l'éditeur.
Généralement appelée *address* ou *affiliation string* dans les métadonnées des publications, et *signature* dans le langage courant (côté auteur).

https://www.uca.fr/recherche/science-ouverte-et-publication/politique-de-signature-des-publications

## APC {#apc}
*Article Processing Charges*. Frais de publication facturés par l'éditeur pour publier un article en accès ouvert. Peut aller de quelques centaines à plusieurs milliers d'euros selon la revue.

## AuréHAL {#aurehal}
Référentiel d'entités HAL (auteurs, structures, revues).

## Collection HAL {#collection-hal}
Sous-portail HAL agrégeant les publications d'une structure (i.e. les publications déposées dans HAL et dont au moins un auteur a une affiliation à cette structure). Chaque collection porte un code, correspondant souvent (mais pas toujours) à l'acronyme du laboratoire.

Exemple: https://hal.science/PIAF

La collection d'une structure tutelle agrège les publications de ses sous-structures. L'arborescence des structures est fournie par le référentiel [[aurehal|AuréHAL]].

## Crossref {#crossref}
Agence d'enregistrement de DOI, principalement pour les publications.

## Datacite {#datacite}
Agence d'enregistrement de DOI, principalement pour les autres types de documents (jeux de données, etc.)

## DOAJ {#doaj}
*Directory of Open Access Journals*. Répertoire des revues en accès ouvert.

https://doaj.org/

## DOI {#doi}
*Digital Object Identifier*. Identifiant unique et pérenne d'une publication (ex: `10.1234/article.5678`).

## Dumas {#dumas}

## HAL {#hal}
Archive ouverte nationale française.

Voir [détails](sources/hal) sur l'API et les données récupérées.

## idHAL {#idhal}
Identifiant auteur dans HAL. Créé par le chercheur dans son profil HAL.

## IdRef {#idref}
Identifiant auteur créé et maintenu par l'ABES (Agence bibliographique de l'enseignement supérieur).

## ISSN {#issn}
*International Standard Serial Number*. Identifiant d'une publication périodique (= revue). Il peut exister un ISSN *print* (pour la version imprimée), un eISSN (pour la version électronique) et un ISSN-L (de liaison: identifiant unique pour une publication multi-supports).

Doc: https://www.issn.org/fr/comprendre-lissn/

## Licences

## NNT {#nnt}
Numéro national de thèse. Identifiant unique pour les thèses.

## OpenAlex {#openalex}
Base bibliographique ouverte (fondation OurResearch): https://openalex.org/

Voir [détails](sources/openalex) sur l'API et les données récupérées.

## OpenAPC {#openapc}

## ORCID {#orcid}
Identifiant unique d'un chercheur (ex: `0000-0001-2345-6789`). Créé par le chercheur.

## Pmid {#pmid}

## Postprint {#postprint}

## Preprint {#preprint}

## ROR {#ror}
*Research Organization Registry*. Registre international des structures de recherche, attribuant des identifiants uniques à chaque structure. (ex: [01a8ajp46](https://ror.org/01a8ajp46) pour l'UCA).

## ScanR {#scanr}
Portail ministériel de la recherche française.

## Theses.fr {#theses-fr}

## Thèses en ligne (TEL) {#tel}

## Unpaywall {#unpaywall}
Service qui résout le statut *open access* de chaque publication à partir du DOI. API utilisée pour enrichir et corriger le champ `oa_status` des publications. Voir [détails](sources/unpaywall).

## Voies *open access* {#oa_status}

On distingue plusieurs "voies" d'*open access* par des noms de couleur, selon le régime juridique. Les deux principales sont le *green open access* (côté auteur: dépôt du *preprint*) et le *gold open access* (côté éditeur: revue nativement OA), mais d'autres sous-catégories ont été distinguées par la suite:


| Voie OA | Définition |
|-------|-----------|
| **Green** | Publication déposée en archive ouverte (HAL, arXiv...), en général par l'auteur, parallèlement à sa publication dans une revue. La version déposée peut être un *preprint* ou un *postprint*. |
| **Gold** | Publication en accès ouvert dans une revue entièrement OA. Généralement payant (APC). |
| **Diamond** | Sous-catégorie du *gold* : Publication dans une revue OA sans paiement d’APC (financement institutionnel). Attention: [Unpaywall](sources/unpaywall) ne distingue pas *diamond* de *gold*. |
| **Hybrid** | Publication en accès ouvert dans une revue sous abonnement payant. L'auteur paie un APC pour rendre son article accessible en OA. Généralement déconseillé (l'institution paye les APC + l'abonnement à la revue). |
| **Bronze** | Publication accessible gratuitement sur le site de l'éditeur, sans licence OA explicite. *Open access* côté éditeur *de facto*, accès sans garantie de pérennité. |

## Web of Science (WoS) {#wos}
Base bibliographique commerciale (*Clarivate*). Une des sources de données bibliographiques moissonnées (tant que l'UCA est abonnée).
Voir [détails](sources/wos) sur l'API et les données récupérées.


## Autres, à déplacer ou supprimer

| Terme | Définition |
|-------|-----------|
| **Éditeur** (publisher) | Maison d'édition scientifique (Elsevier, Springer Nature, EDP Sciences...). |
| **Revue** (journal) | Périodique scientifique identifié par un ou plusieurs ISSN. Rattaché à un éditeur. |
| **Auteur correspondant** | Auteur désigné comme contact principal pour une publication. Il peut y en avoir plusieurs. |
| **Premier auteur / dernier auteur** | Conventions de signature scientifique : le premier auteur a généralement fait le travail principal ; le dernier auteur est souvent le directeur de l'équipe. Notion pertinente dans les disciplines STEM. |

| Terme | Définition |
|-------|-----------|
| **Article** | Publication dans une revue à comité de lecture. Type le plus courant. |
| **Review** | Article de synthèse (revue de la littérature). Attention : dans WoS, "book review" désigne un compte-rendu d'ouvrage, pas une revue de la littérature. |
| **Conference paper** | Communication dans un colloque ou une conférence. Inclut les posters dans certaines sources. |
| **Preprint** | Version pré-publication déposée avant peer review (arXiv, HAL, etc.). |

*TODO: étoffer*


| Terme | Définition |
|-------|-----------|
| **Authorship** | <span id="authorship"></span>Pas un terme métier mais omniprésent dans l'appli. Couple (publication, personne) représentant la contribution d'**un** auteur à **une** publication. Porte les informations d'affiliation (structures UCA), de position (rang dans la liste d'auteurs) et le flag `in_perimeter`. |
| **Périmètre** | Ensemble de *n* structures, incluant leurs sous-structures. Deux périmètres sont définis: UCA (contient l'UCA et ses labos en tutelle directe), UCA élargi (contient le précédent + CHU + INP). |
