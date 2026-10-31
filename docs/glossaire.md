# Glossaire métier

## ABES
*Agence bibliographique de l'enseignement supérieur*. Gère le Sudoc, IdRef et theses.fr.

## Adresse
Chaîne de caractères qui donne l'[affiliation](#affiliation) d'un auteur dans une publication, fournie par l'auteur à l'éditeur. Appelée *address* ou *affiliation string* dans les métadonnées, et *signature* dans le langage courant.

## Affiliation
Structure ou structures de rattachement d'un auteur dans une publication. Elle est liée au couple personne-publication, et non à la personne.

## APC
*Article Processing Charges*. Frais facturés par l'éditeur pour publier un article en open access, de quelques centaines à plusieurs milliers d'euros selon la revue. Dans une revue entièrement open access, on parle d'open access gold ; dans une revue sous abonnement, de modèle hybride. Voir [voies *open access*](#voies-open-access).

## Article
Publication dans une revue à comité de lecture.

## AuréHAL
Référentiel d'entités de HAL : auteurs, structures, revues.

## Auteur correspondant
Auteur désigné comme contact principal de l'éditeur. Une publication en a parfois deux ou trois. Les [APC](#apc) sont en général payés par la structure de rattachement de l'auteur correspondant. Les sources renseignent inégalement cette information.

## Collection HAL
Sous-portail HAL qui réunit les publications d'une structure : les dépôts avec au moins un auteur affilié à cette structure. Chaque collection a un code, souvent l'acronyme du laboratoire (exemple : https://hal.science/PIAF). La collection d'une tutelle réunit les publications de ses sous-structures, d'après l'arborescence d'[AuréHAL](#auréhal).

## Communication
Contribution à un colloque ou une conférence (*conference paper*). Certaines sources y rangent les posters.

## Contribution
Participation d'une personne à une publication, avec ses [affiliations](#affiliation). Elle réunit les mentions de cette personne dans les différentes sources, et désigne la personne quand elle est identifiée. Voir le [modèle de données](donnees/04-contributions.md).

## Crossref
Agence d'enregistrement de DOI, surtout pour les publications d'éditeurs. Voir [détails](sources/06-crossref.md).

## DataCite
Agence d'enregistrement de DOI, surtout pour les jeux de données, logiciels et dépôts d'entrepôts. Voir [détails](sources/07-datacite.md).

## DOAJ
*Directory of Open Access Journals*. Répertoire des revues en open access : https://doaj.org/

## DOI
*Digital Object Identifier*. Identifiant unique et pérenne d'un document (ex. : `10.1234/article.5678`).

## DUMAS
*Dépôt universitaire de mémoires après soutenance*. Portail de HAL pour les mémoires d'étudiants. Les mémoires restent hors des publications.

## Éditeur
Maison d'édition scientifique (Elsevier, Springer Nature, EDP Sciences…), qui publie les documents et reçoit les frais de publication.

## HAL
Archive ouverte nationale française. Voir [détails](sources/02-hal.md).

## idHAL
Identifiant d'auteur dans HAL, créé par le chercheur dans son profil HAL.

## IdRef
*Identifiants et référentiels pour l'enseignement supérieur et la recherche*. Référentiel d'autorités (personnes, collectivités…) de l'ABES : https://www.idref.fr/. Un identifiant IdRef, ou PPN, compte 9 caractères : 8 chiffres et une clé, chiffre ou `X`.

## ISSN
*International Standard Serial Number*. Identifiant d'une publication en série. Une revue peut avoir un ISSN imprimé, un eISSN (version électronique) et un ISSN-L, qui relie les supports d'une même revue : https://www.issn.org/fr/comprendre-lissn/

## Licences
Conditions de réutilisation d'une publication, le plus souvent une licence Creative Commons (CC BY, CC BY-NC…).

## NNT
Numéro national de thèse. Identifiant unique d'une thèse soutenue.

## OpenAlex
Base bibliographique ouverte (fondation OurResearch) : https://openalex.org/. Voir [détails](sources/03-openalex.md).

## OpenAPC
Jeu de données ouvert des frais de publication payés par les établissements participants. Voir [données APC](sources/10-imports-manuels.md#données-apc).

## ORCID
Identifiant unique d'un chercheur (ex. : `0000-0001-2345-6789`), créé par le chercheur lui-même.

## Organisation partenaire
Organisation [ROR](#ror) d'un auteur d'une publication, ou ancêtre ROR de cette organisation. Les organisations partenaires excluent les structures étudiées, leurs tutelles et leurs ancêtres ROR. Les structures étudiées sont le laboratoire de la page, les laboratoires sélectionnés, ou à défaut tout le périmètre.

## PID
*Persistent identifier*. Identifiant unique et pérenne d'une entité.

| Entité | Exemples d'identifiants |
|---|---|
| Personne | [ORCID](#orcid), [IdRef](#idref) |
| Structure | [ROR](#ror) |
| Publication | [DOI](#doi) |
| Revue | [ISSN](#issn) |

## PMID
Identifiant d'un article dans [PubMed](#pubmed).

## Postprint
Version d'un article acceptée pour publication, après évaluation par les pairs.

## Premier auteur, dernier auteur
Conventions de signature : le premier auteur a en général fait le travail principal, le dernier dirige souvent l'équipe. Elles valent surtout en sciences, techniques et médecine.

## Preprint
Version d'un article avant évaluation par les pairs.

## Publication en série
Support qui réunit des documents sous un même titre : revue, collection d'ouvrages, recueil d'actes, média. Elle est rattachée à un éditeur.

## PubMed
Base bibliographique biomédicale de la bibliothèque nationale de médecine des États-Unis.

## PubMed Central (PMC)
Archive en texte intégral de la bibliothèque nationale de médecine des États-Unis. Un article de PMC a un identifiant PMCID.

## RAMEAU
*Répertoire d'autorité-matière encyclopédique et alphabétique unifié*. Vocabulaire d'indexation des bibliothèques françaises, géré par la BnF, employé par le Sudoc et theses.fr.

## Revue
Publication en série périodique, identifiée par un ou plusieurs [ISSN](#issn).

## ROR
*Research Organization Registry*. Registre international des organisations de recherche, qui attribue un identifiant unique à chacune (ex. : [02feahw73](https://ror.org/02feahw73) pour le CNRS).

## ScanR
Portail du ministère de l'Enseignement supérieur et de la Recherche sur la recherche française. Voir [détails](sources/05-scanr.md).

## Synthèse
Article de synthèse, ou revue de la littérature (*review*). Dans WoS, *book review* désigne un compte rendu d'ouvrage.

## theses.fr
Portail de l'ABES des thèses françaises, soutenues et en préparation. Voir [détails](sources/08-theses.md).

## Thèses en ligne (TEL)
Portail de HAL pour les thèses de doctorat et les habilitations à diriger des recherches.

## Unpaywall
Service qui trouve les versions open access d'un document identifié par un DOI. Voir [détails](sources/09-sources-supplementaires.md#unpaywall).

## Voies *open access*
Les voies d'open access se nomment par des couleurs, selon le régime de diffusion. Les deux principales sont le *green* (dépôt de l'auteur dans une archive ouverte) et le *gold* (revue entièrement open access).

| Voie | Définition |
|---|---|
| **Green** | Publication déposée en archive ouverte (HAL, arXiv…), en général par l'auteur, en plus de sa publication dans une revue. La version déposée peut être un *preprint* ou un *postprint*. |
| **Gold** | Publication en open access dans une revue entièrement open access, souvent contre des APC. |
| **Diamond** | Sous-catégorie du *gold* : publication dans une revue sans APC ni autres frais. Une revue est diamant quand elle est marquée comme telle dans le référentiel, ou quand le DOAJ la donne sans frais. [Unpaywall](sources/09-sources-supplementaires.md#unpaywall) ne distingue pas *diamond* de *gold*. |
| **Hybrid** | Publication en open access dans une revue sous abonnement, contre des APC. |
| **Bronze** | Publication lisible gratuitement sur le site de l'éditeur, sans licence open access explicite ni garantie de pérennité. |

## Web of Science (WoS)
Base bibliographique commerciale de Clarivate. Voir [détails](sources/04-wos.md).
