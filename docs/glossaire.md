# Glossaire métier

*A compléter*

## ABES {#abes}
*Agence bibliographique de l'Enseignement supérieur*

## Adresse {#adresse}
Chaîne de caractères associée à une publication et signalant l'[affiliation](glossaire.md#affiliation) institutionnelle de chaque auteur. Fournie par chaque auteur à l'éditeur.
Généralement appelée *address* ou *affiliation string* dans les métadonnées des publications, et *signature* dans le langage courant (côté auteur).

https://www.uca.fr/recherche/science-ouverte-et-publication/politique-de-signature-des-publications

## Affiliation {#affiliation}
Information sur la ou les structure(s) de rattachement de chaque auteur d'une publication.

Elle est liée à un couple personne-publication, et non à une personne en tant que telle.

## APC {#apc}
*Article Processing Charges*. Frais de publication facturés par l'éditeur pour publier un article en accès ouvert. Peuvent aller de quelques centaines à plusieurs milliers d'euros selon la revue.

Si la revue est *full open access*, on parle d'*open access gold*. Si la revue est sous abonnement, on parle de modèle hybride. Voir [voies *open access*](glossaire.md#oa_status).

## AuréHAL {#aurehal}
Référentiel d'entités HAL (auteurs, structures, revues).

## Auteur correspondant {#auteur-correspondant}

Auteur désigné comme contact principal de l'éditeur pour une publication à plusieurs auteurs. Il y en a parfois deux ou trois sur une même publication.

Les [APC](glossaire.md#apc) (si présents) sont payés par la structure de rattachement de l'auteur correspondant.

L'information "auteur correspondant" est inégalement renseignée dans les métadonnées des sources.

## Authorship {#authorship}
Couple personne-publication, représentant la contribution d'un auteur et portant une [affiliation](glossaire.md#affiliation) institutionnelle. Pas un terme métier mais notion présente dans les métadonnées sources et dans le code.

## Collection HAL {#collection-hal}
Sous-portail HAL agrégeant les publications d'une structure (i.e. les publications déposées dans HAL et dont au moins un auteur a une affiliation à cette structure). Chaque collection porte un code, correspondant souvent à l'acronyme du laboratoire.

Exemple: https://hal.science/PIAF

La collection d'une structure tutelle agrège les publications de ses sous-structures. L'arborescence des structures est fournie par le référentiel [AuréHAL](glossaire.md#aurehal).

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

Voir [détails](sources/02-hal.md) sur l'API et les données récupérées.

## idHAL {#idhal}
Identifiant auteur dans HAL. Créé par le chercheur dans son profil HAL.

## IdRef {#idref}
**Id**entifiants et **Réf**érentiels pour l'Enseignement supérieur et la Recherche. Référentiel d'autorités (personnes, collectivités, etc.) développé et maintenu par l'ABES. https://documentation.abes.fr/aideidref/accueil/fr/index.html

Par raccourci de langage on parle d'*identifiants IdRef* pour désigner les identifiant de ce référentiel. Officiellement on parle de *n° PPN*. Il est composé de 9 caractères (8 chiffres + 1 clé pouvant être un chiffre ou un 'X').

## ISSN {#issn}
*International Standard Serial Number*. Identifiant d'une publication périodique (= revue). Il peut exister un ISSN *print* (pour la version imprimée), un eISSN (pour la version électronique) et un ISSN-L (de liaison: identifiant unique pour une publication multi-supports).

Doc: https://www.issn.org/fr/comprendre-lissn/

## Licences

## NNT {#nnt}
Numéro national de thèse. Identifiant unique pour les thèses.

## OpenAlex {#openalex}
Base bibliographique ouverte (fondation OurResearch): https://openalex.org/

Voir [détails](sources/03-openalex.md) sur l'API et les données récupérées.

## OpenAPC {#openapc}

## ORCID {#orcid}
Identifiant unique d'un chercheur (ex: `0000-0001-2345-6789`). Créé par le chercheur.

## PID {#pid}

*Persistent identifier*. Identifiant unique pour une entité donnée.
|Entité|Exemples d'identifiants|
|---|------|
|Personne|[ORCID](glossaire.md#orcid), [IdRef](glossaire.md#idref)|
|Structure|[ROR](glossaire.md#ror)|
|Publication|[DOI](glossaire.md#doi)|
|Revue|[ISSN](glossaire.md#issn)|

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
Service permettant de trouver des versions *open access* de publications académiques identifiées par un DOI. API utilisée pour enrichir et corriger le champ `oa_status` des publications. Voir [détails](sources/08-sources-supplementaires.md#unpaywall).

## Voies *open access* {#oa_status}

On distingue plusieurs "voies" d'*open access* par des noms de couleur, selon le régime juridique. Les deux principales sont le *green open access* (côté auteur: dépôt du *preprint*) et le *gold open access* (côté éditeur: revue nativement OA), mais d'autres sous-catégories ont été distinguées par la suite:


| Voie OA | Définition |
|-------|-----------|
| **Green** | Publication déposée en archive ouverte (HAL, arXiv...), en général par l'auteur, parallèlement à sa publication dans une revue. La version déposée peut être un *preprint* ou un *postprint*. |
| **Gold** | Publication en accès ouvert dans une revue entièrement OA. Généralement payant (APC). |
| **Diamond** | Sous-catégorie du *gold* : Publication dans une revue OA sans paiement d’APC (financement institutionnel). Attention: [Unpaywall](sources/08-sources-supplementaires.md#unpaywall) ne distingue pas *diamond* de *gold*. |
| **Hybrid** | Publication en accès ouvert dans une revue sous abonnement payant. L'auteur paie un APC pour rendre son article accessible en OA. Généralement déconseillé (l'institution paye les APC + l'abonnement à la revue). |
| **Bronze** | Publication accessible gratuitement sur le site de l'éditeur, sans licence OA explicite. *Open access* côté éditeur *de facto*, accès sans garantie de pérennité. |

## Web of Science (WoS) {#wos}
Base bibliographique commerciale (*Clarivate*). Une des sources de données bibliographiques moissonnées (tant que l'UCA est abonnée).
Voir [détails](sources/04-wos.md) sur l'API et les données récupérées.


## Autres, à déplacer ou supprimer

| Terme | Définition |
|-------|-----------|
| **Éditeur** (publisher) | Maison d'édition scientifique (Elsevier, Springer Nature, EDP Sciences...). |
| **Revue** (journal) | Périodique scientifique identifié par un ou plusieurs ISSN. Rattaché à un éditeur. |
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
| **Périmètre** | Ensemble de *n* structures, incluant leurs sous-structures. Deux périmètres sont définis: UCA (contient l'UCA et ses labos en tutelle directe), UCA élargi (contient le précédent + CHU + INP). |
