# Chantier — Adresses décalées chez OpenAlex

## Contexte

Dans certains enregistrements sources OpenAlex, le décalage commence à un auteur collectif de la liste des auteurs. L'auteur collectif reçoit l'adresse de la contribution source suivante. Chaque contribution source suivante reçoit son adresse et celle de la contribution source d'après. Le décalage touche les chaînes d'affiliation (`raw_affiliation_strings`) et les institutions, donc les ROR. Exemple, l'œuvre W2982537460 de la publication 184877 :

| Position OpenAlex | Auteur | Adresses OpenAlex | Adresse WoS |
|---|---|---|---|
| 0 | « on behalf of the Société… » (collectif) | CHU Grenoble | |
| 1 | C. Deteix | CHU Grenoble, Agence de la biomédecine | CHU Grenoble |
| 2 | F. Mesnil | Agence de la biomédecine, Institut Paoli-Calmettes | Agence de la biomédecine |
| 3 | S. Fürst | Institut Paoli-Calmettes, CHU Bordeaux | Institut Paoli-Calmettes |
| 4 | N. Milpied | CHU Bordeaux, CHRU Lille | CHU Bordeaux |

Crossref ne donne aucune affiliation pour cet article.

Un second défaut donne à chaque contribution source toutes les adresses de l'article, notes de bas de page comprises (« Submitted for publication… », « Address correspondence to… »).

### Mesures du 2026-11-27

Scripts dans `data/experiments/decalage-adresses-openalex/` : `decalage.py` (mesure), `detail.py` (adresses d'un enregistrement source), `payload.py` (payload brut d'une œuvre). Enregistrements sources décalés dans `decales.csv`.

Critère du décalage. L'adresse reportée se calcule de proche en proche : la contribution source 0 reporte toutes ses adresses brutes ; la contribution source i reporte les siennes moins l'adresse reportée par i − 1, à défaut l'adresse reportée par i − 1. Dans un enregistrement source décalé, l'adresse de la contribution source i est celle reportée par i − 1. Une paire de contributions sources consécutives est décalée quand i contient l'adresse reportée par i − 1 et une autre adresse, contraire quand i perd l'adresse reportée par i − 1. Un enregistrement source est décalé quand 80 % de ses paires décalées ou contraires sont décalées, sur 3 paires au moins, et quand une contribution source reçoit en moyenne moins de la moitié des adresses de l'enregistrement source. Toutes les adresses vont à chacun quand une contribution source en reçoit en moyenne 90 % au moins, sur 4 adresses au moins.

Enregistrements sources de 4 à 200 auteurs :

| | OpenAlex | WoS (témoin) |
|---|---|---|
| Examinés | 30 016 | 19 346 |
| Décalés | 47 | 2 |
| Toutes les adresses à chacun | 46 | 3 |

- Sur les payloads bruts (`decalage_payloads.py`), 3 des 3 057 œuvres d'une publication à enregistrement source INSPIRE-HEP et 4 des 730 œuvres de plus de 200 auteurs sont décalées. Ces œuvres sont hors de la mesure en base : sans contribution source pour les premières, au-delà de 200 auteurs pour les secondes.
- 24 des 47 enregistrements sources décalés ont un auteur collectif en position 0. Un quart des 96 enregistrements sources OpenAlex à auteur collectif en position 0 sont décalés.
- Dans d'autres, le décalage commence après un auteur collectif placé plus loin, non reconnu comme collectif (`collective`) : « MacaqueNet » en position 2 de W4407421416.
- 46 contributions sources sont du périmètre par la seule adresse de la contribution source suivante, dans 38 enregistrements sources décalés.
- Les enregistrements sources à toutes les adresses pour chacun contiennent 165 contributions sources du périmètre, légitimes ou non.

## Décisions

- Les adresses décalées se corrigent : chaque contribution source garde sa seule adresse.
- Le défaut est signalé à OpenAlex, avec la méthode de correction.

## Phasage

### Phase 1 — Détection

- [ ] Règle du domaine : détection du décalage sur les adresses brutes d'un enregistrement source, par position.
- [ ] Point de départ du décalage : un auteur collectif, reconnu ou non, ou la première paire décalée.
- [ ] Revue des 47 enregistrements sources décalés et des enregistrements sources de score 0,5 à 0,8.

### Phase 2 — Correction à la normalisation d'OpenAlex

- [ ] Adresses brutes : chaque contribution source garde l'adresse reportée par la précédente ; l'auteur collectif n'en garde aucune.
- [ ] Institutions et ROR : même correction.
- [ ] Effet sur le stock : contributions sources et publications qui sortent du périmètre.
- [ ] Reprise du stock : réhydratation des seuls enregistrements sources concernés (`rehydrate_staging_from_raw_store.py --resync-contributions`), puis normalisation. Le script sélectionne par préfixe d'identifiant ou par type de document : une sélection par liste est à ajouter.

### Phase 3 — Toutes les adresses à chacun

- [ ] Revue des 46 enregistrements sources.
- [ ] Traitement de leurs adresses.

### Phase 4 — Signalement à OpenAlex

- [ ] Ticket sur openalex.org/contact : exemples, critère, méthode de correction.

### Phase 5 — Documentation

- [ ] Mise à jour de la documentation : normalisation d'OpenAlex.

## Questions ouvertes

- Reconnaissance des auteurs collectifs : « MacaqueNet » et noms de réseaux semblables.
