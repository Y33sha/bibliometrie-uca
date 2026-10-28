# Pipeline
* [ ] bloquer les opérations destructrices côté admin lorsque le pipeline est actif (recenser les actions qui peuvent poser problème)
## Extraction
* [ ] bioRxiv, medRxiv: voir si on moissonne ces identifiants; possibilité de récupérer les DOI à partir des identifiants comme dans ArXiv? (ex. publi 2757)
* [ ] API de détail des thèses (https://theses.fr/api/v1/theses/these/{nnt}): utiliser le champ cas (cas1 à cas6) pour distinguer les thèses sous embargo vs fermées sur décision du déposant. (+ récupérer champ langue)
* [ ] Dimensions?; ArXiv, PMC, Pubmed; Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS?
## Suite du traitement
* [ ] déduplication par métadonnées: ajouter condition journal_id pour les articles? container title pour les chapitres?
* [ ] règles de priorité entre sources pour les métadonnées: assouplir selon les cas de figure (notice OpenAlex ou ScanR dérivées de HAL => HAL doit primer) / annoter un corpus et trouver une bonne fonction de décision

# Données
* [ ] publi 106296: gérer les adresses résultant d'une erreur de parsing (à quel niveau: exclure adresses? exclure source_contributions? - gestion manuelle, détection automatisée) / Cf personne 62293
* [ ] conserver l'historique des structures
* [ ] identifiants mal placés et neutralisés par le pipeline: auditer
* [ ] récupérer date de publication complète au lieu de l'année seule
* [ ] "Additional file" sur figshare: comment regrouper les pièces liées à un même article?

# UI
## Admin
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA")
* [ ] fusionner structures
## Publique
* [ ] page "affiliations suspectes hal": requête incorrecte, capture trop de publis
* [ ] Filtres supplémentaires possibles: `has_doi` (crossref, datacite, other, none); repositories; `corresponding_is_in_perimeter`; `peer_reviewed`? (suppose de posséder la donnée ou de pouvoir la déduire des sources); premier/dernier auteur (sur l'onglet publications de la page personne); impact (citations, fwci, top10)

# Cas particuliers, bizarreries à élucider
* problèmes de fusion
    * [ ] 30172 un recueil de proceedings fusionné avec tous ses chapitres
    * [ ] 182637 et 182636: vérifier si DataCite indique relation
    * [ ] fusion entre article et conference_paper: 12362
    * [ ] 165425: fusion d'un article et d'un dataset
    * 138474: 1 seul document alors que le preprint devrait être distinct
    * 116323: comment empêcher la fusion de l'ouvrage et de ses chapitres?
* [ ] « Daniel Régnier-Roux » incompatible avec la personne 2958 (« daniel roux ») Identifiant hal_person_id='1169' déjà attribué à person_id=2958 avec statut 'pending' ; impossible d'attribuer à person_id=44830. (Correct par hasard; mais l'incompatibilité est anormale)
* 206321: pourquoi UNH non reconnue?
* 81408: openalex, source hal; mais pas de doc hal correpondant

# Idées pour plus tard, éventuellement
## Fonctionnalités
* financements (projets ANR, projets européens)
* stats en compte fractionnaire vs compte entier
* collaborations nationales et internationales: identification des structures partenaires; évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation animée par année)
* définir des groupes de pays (UE, continents) pour la facette "pays des co-auteurs"
* OpenAPC: j'ai utilisé les données sur les APC UCA, mais il faudrait partir du dump complet et matcher tous les DOI des publis UCA pour voir quels établissements ont payé les APC quand ce n'est pas l'UCA
## Détails techniques
* mettre en place des slugs pour les URL (au moins pour labos et personnes)?
