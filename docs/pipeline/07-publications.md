# Création et résolution des publications

*À jour le 2026-10-30.*

La phase `publications` maintient les [publications](../donnees/03-publications.md) à partir des enregistrements sources. Une publication regroupe tous les enregistrements sources qui décrivent le même document, quelles que soient leurs sources. La phase rattache chaque enregistrement source à sa publication, en crée une au besoin, et fusionne ou scinde les publications existantes quand le regroupement le commande.

## Reconnaître la même publication

Deux enregistrements sources désignent la même publication s'ils partagent une **clé de confirmation**.

- **Identifiants** : DOI, NNT (numéro national de thèse), identifiant HAL, PMID (PubMed), identifiant arXiv. Égalité directe. Seuls comptent les identifiants actifs ; un DOI `related` désigne une autre œuvre et reste hors des clés. Le DOI d'une forme secondaire (version, variante) cède la place à sa cible (`doi_targets`).
- **Bloc de métadonnées** : le triplet `type de document | titre normalisé | année`. Deux documents de même type, même titre et même année sont tenus pour identiques. Une longueur minimale de titre écarte les collisions de titres trop génériques.

`domain/source_records/keys.py` calcule ces clés, à partir des métadonnées et des identifiants que la phase `metadata_correction` laisse actifs.

## Regrouper, puis rattacher

Les enregistrements sources reliés par au moins une clé partagée forment les **composantes connexes** d'un graphe.

Une règle prime sur le regroupement : **deux ancres distinctes désignent deux documents distincts**. Les ancres d'une composante sont ses DOI `primary` ou `derived`, à défaut les DOI des enregistrements sources qui en ont un seul. Une composante à plusieurs ancres est découpée en une partition par ancre. Un enregistrement source rejoint l'ancre de son DOI `primary` ou `derived`, sinon l'unique ancre parmi ses autres DOI. À défaut, il reste sur sa publication.

Chaque partition aboutit à une seule publication :

- **Rattachement** : la partition contient une publication existante. Tous ses enregistrements sources y sont rattachés.
- **Fusion** : la partition réunit plusieurs publications existantes. Une seule est conservée, les autres sont absorbées.
- **Scission** : une publication existante est à cheval sur plusieurs partitions. Elle reste sur l'une d'elles, et une publication est créée pour chacune des autres.
- **Création** : la partition ne contient aucune publication. Une publication est créée si au moins un enregistrement source de la partition est dans le périmètre.
- **Sans suite** : à défaut, les enregistrements sources de la partition restent orphelins.

Le périmètre conditionne seulement la création : un enregistrement source hors périmètre peut rejoindre une publication existante.

*Chaque sommet du graphe est un enregistrement source. Une arête pleine relie deux enregistrements sources qui partagent une clé de confirmation. Une ligne en pointillés rattache un enregistrement source à sa publication (boîtes).*

![Graphe de résolution : enregistrements sources reliés par clés partagées, partitionnés puis rattachés à des publications](../img/graphs/reconciliation.png)

## Traitement incrémental

Un enregistrement source modifié (inséré, normalisé de nouveau, corrigé) est marqué *à recalculer*. La phase traite seulement le **voisinage direct** de ces enregistrements sources, c'est-à-dire ceux qui partagent une clé avec eux.

Après une modification de la logique de résolution, l'option `--rebuild-publications` marque toutes les publications *à recalculer*, pour appliquer le changement au stock.

## Recalcul des métadonnées

Les métadonnées de chaque publication touchée sont recalculées depuis ses enregistrements sources. L'éditeur est celui de la date de publication : le titulaire du préfixe du DOI Crossref, à défaut le premier éditeur des enregistrements sources selon le classement des sources. Une publication sans enregistrement source est supprimée.
