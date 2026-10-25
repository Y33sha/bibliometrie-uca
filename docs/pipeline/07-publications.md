#  Création et résolution des publications

*À jour le 2026-10-25.*

```mermaid
flowchart LR
    A@{ shape: procs, label: "source_records"}-->B[publications]
    classDef new  fill:#bbf
    class B new;
```

Phase `publications` : maintient le référentiel `publications` à partir des `source_records`. Une publication regroupe toutes les `source_records` qui attestent du même document, quelles que soient leurs sources. La phase rattache chaque `source_record` à la bonne publication, en crée une lorsqu'aucune ne convient, et fusionne ou scinde les publications existantes quand le regroupement le commande.

## Reconnaître la même publication

Deux `source_records` désignent la même publication si elles partagent une **clé de confirmation**.

- **Identifiants** : DOI, NNT (numéro national de thèse), identifiant HAL, PMID (PubMed), identifiant arXiv. Égalité directe.
- **Bloc de métadonnées** : le triplet `type de document | titre normalisé | année`. Deux documents de même type, même titre et même année sont tenus pour identiques. Une longueur minimale de titre écarte les collisions de titres trop génériques.

Ces clés sont projetées par `domain/source_records/keys.py`, à partir des colonnes déjà normalisées (phase `normalize`) puis corrigées (phase `metadata_correction`).

## Regrouper, puis assigner

Les `source_records` reliées par au moins une clé partagée forment les **composantes connexes** d'un graphe.

Une règle prime sur le regroupement : **deux DOI distincts ne désignent jamais le même document**. Une composante qui porte plusieurs DOI est donc découpée en une partition par DOI.

Chaque partition aboutit sur une seule publication. Cas de figure possibles :

- **Rattachement** : la partition contient déjà une publication existante → toutes ses `source_records` y sont rattachées.
- **Fusion** : la partition réunit plusieurs publications existantes → une seule est conservée, les autres sont absorbées.
- **Scission** : une publication existante se retrouve à cheval sur plusieurs partitions → elle reste sur une seule d'entre elles, et une publication est créée pour chacune des autres.
- **Création** : la partition ne contient aucune publication existante → une publication est créée si au moins une `source_record` de la partition est dans le périmètre.
- **Sans suite** : à défaut, les `source_records` de la partition restent orphelines.

Le périmètre ne conditionne que la création : une `source_record` hors périmètre peut se rattacher à une publication existante.

*Chaque nœud est une `source_record`, chaque arête pleine relie deux `source_records` qui partagent une clé de confirmation, chaque ligne en pointillés rattache une `source_record` à sa publication (boîtes).*

![Graphe de résolution : source_records reliées par clés partagées, partitionnées puis rattachées à des publications](../img/graphs/reconciliation.png)


## Traitement incrémental

Une `source_record` modifiée (insérée, re-normalisée, corrigée) est marquée *à recalculer*, et la phase ne traite que le **voisinage direct** de ces `source_records` — celles avec lesquelles elles partagent une clé.

> **Conséquence** :
> Après toute modification de la logique de résolution, il faut marquer toutes les publications *à recalculer* pour que le changement s'applique à tout le stock : lancer le pipeline avec l'option `--rebuild-publications`.

## Rafraîchissement des métadonnées

Une fois les rattachements posés, les métadonnées de chaque publication touchée sont recalculées par agrégation de ses `source_records`. La licence de la version éditeur (`license`) suit un ordre de sources propre, et la licence du fichier déposé (`deposit_license`) vient de HAL. L'éditeur est celui de la date de publication : le titulaire du préfixe du DOI Crossref, à défaut le premier éditeur des enregistrements sources selon le classement des sources. Le préfixe d'une plateforme d'éditeurs ne compte pas, et une production hébergée sans être publiée n'a pas d'éditeur (`domain/publishers/attribution.py`). Les publications vidées de toutes leurs `source_records` sont supprimées.
