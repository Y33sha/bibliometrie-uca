# Pipeline
## Extraction
* [ ] Sudoc? Cairn, Persée pour augmenter couverture SHS?
* [ ] payloads bruts: ne plus faire transiter par la base?
* [ ] openalex: chercher par ROR plutôt que par i***?
## Suite du traitement
* [ ] normalisation en parallèle de l'extraction?
* [ ] déduplication par métadonnées: ajouter condition journal_id pour les articles? container title pour les chapitres?
* [ ] règles de priorité entre sources pour les métadonnées: assouplir selon les cas de figure (notice OpenAlex ou ScanR dérivées de HAL => HAL doit primer) / annoter un corpus et trouver une bonne fonction de décision
# Données
* [ ] conserver l'historique des structures + possibilité de fusionner des structures
* [ ] publications fermées, sans localisation éditeur, avec revue OA: chercher des moyens de retrouver les localisations éditeur (URL des revues)
* [ ] revue dans une liste officielle, avec type autre que "revue": auditer
* [ ] personnes: stocker les dates min et max des contributions dans le périmètre, pour filtrer les auteurs par période d'activité
* [ ] référentiel des conférences?
* [ ] colonne BOOL deprecated dans person_identifiers (masquer de l'UI)
# UI
## Admin
* [ ] bloquer les opérations destructrices côté admin lorsque le pipeline est actif (recenser les actions qui peuvent poser problème)
* [ ] page bilan pipeline à toiletter
## Publique
* [ ] stats en compte fractionnaire vs compte entier?
* [ ] quand on détache une publi d'un auteur: mettre à jour le décompte et la pagination
### Visualisation
* [ ] évolution des collaborations dans le temps (graphes de collaboration par labo, avec visualisation par année)