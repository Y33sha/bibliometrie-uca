# Pipeline
## Extraction
* [ ] Dimensions?; Sudoc? (liens personnes-thèses plus complets que theses.fr, j'ai l'impression); Cairn, Persée pour augmenter couverture SHS? creuser ISTEX
* [ ] payloads bruts: ne plus faire transiter par la base?
## Suite du traitement
* [ ] normalisation en parallèle de l'extraction?
* [ ] déduplication par métadonnées: ajouter condition journal_id pour les articles? container title pour les chapitres?
* [ ] règles de priorité entre sources pour les métadonnées: assouplir selon les cas de figure (notice OpenAlex ou ScanR dérivées de HAL => HAL doit primer) / annoter un corpus et trouver une bonne fonction de décision
# Données
* [ ] conserver l'historique des structures
* [ ] financements (projets ANR, projets européens)
* [ ] publications fermées, sans localisation éditeur, avec revue OA: chercher des moyens de retrouver les localisations éditeur (URL des revues)
* [ ] revue dans une liste officielle, avec type autre que "revue": auditer
# UI
## Admin
* [ ] créer des catégories de personnes (personnel UCA, chercheurs associés, anciens doctorants, méga-collab de physique des particules) => et pouvoir configurer la visibilité des groupes dans l'UI publique (beaucoup d'adresses UCA dans les collaborations ALICE/ATLAS sont décalées dans les sources, ce qui pourrit la base avec des milliers de fausses "personnes UCA")
* [ ] fusionner structures
* [ ] bloquer les opérations destructrices côté admin lorsque le pipeline est actif (recenser les actions qui peuvent poser problème)
## Publique
* [ ] auteur premier, dernier, correspondant: sur les facettes et les stats
* [ ] stats en compte fractionnaire vs compte entier?
* [ ] quand on détache une publi d'un auteur: mettre à jour le décompte et la pagination
* [ ] page publisher: pas de tab monographies si count=0
### Visualisation
* [ ] taux de collaboration
* [ ] évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation animée par année)
* [ ] visualisation des collab avec carte (monde, Europe, France) qui les localise au niveau de leur ville

# Cas particuliers, bizarreries à élucider
* "How Self-Location Predicts the Degree and Quality of the Felt Sense of Connection" => preprint de ... (DOI non résolu) + lien open access renvoie sur la v1
