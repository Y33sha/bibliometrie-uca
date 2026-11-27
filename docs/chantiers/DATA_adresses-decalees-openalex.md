# Chantier — Adresses décalées chez OpenAlex

## Contexte

Dans certains enregistrements sources OpenAlex, la liste des auteurs et celle des affiliations sont décalées d'un rang à partir d'une position. Chaque contribution source reçoit alors son adresse et celle d'une voisine. Le décalage touche les chaînes d'affiliation (`raw_affiliation_strings`) et les institutions, donc les ROR. Il a deux sens :

- auteur inséré, le plus souvent un auteur collectif : l'auteur inséré reçoit l'adresse de la contribution source suivante, et chaque contribution source après lui reçoit son adresse et celle de la suivante ;
- auteur manquant : chaque contribution source reçoit son adresse et celle de la précédente. Dans W4310125553 (doi:10.1182/blood-2022-159125), la numérotation des affiliations montre l'affiliation n° 5 d'un auteur absent de la liste.

Exemple d'auteur inséré, l'œuvre W2982537460 de la publication 184877 :

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

Scripts dans `data/experiments/decalage-adresses-openalex/` : `decalage.py` (mesure), `sens.py` (sens du décalage d'après WoS), `detail.py` (adresses d'un enregistrement source), `payload.py` (payload brut d'une œuvre). Enregistrements sources décalés dans `decales.csv`.

Critère du décalage. L'adresse reportée se calcule de proche en proche : la contribution source 0 reporte toutes ses adresses brutes ; la contribution source i reporte les siennes moins l'adresse reportée par i − 1, à défaut l'adresse reportée par i − 1. Dans un enregistrement source décalé, l'adresse de la contribution source i est celle reportée par i − 1 pour un auteur inséré, celle reportée par i pour un auteur manquant. Une paire de contributions sources consécutives est décalée quand i contient l'adresse reportée par i − 1 et une autre adresse, contraire quand i perd l'adresse reportée par i − 1. Un enregistrement source est décalé quand 80 % de ses paires décalées ou contraires sont décalées, sur 3 paires au moins, et quand une contribution source reçoit en moyenne moins de la moitié des adresses de l'enregistrement source. Toutes les adresses vont à chacun quand une contribution source en reçoit en moyenne 90 % au moins, sur 4 adresses au moins.

Enregistrements sources de 4 à 200 auteurs :

| | OpenAlex | WoS (témoin) |
|---|---|---|
| Examinés | 30 016 | 19 346 |
| Décalés | 47 | 2 |
| Toutes les adresses à chacun | 46 | 3 |

- Sur les payloads bruts (`decalage_payloads.py`), 3 des 3 057 œuvres d'une publication à enregistrement source INSPIRE-HEP et 4 des 730 œuvres de plus de 200 auteurs sont décalées. Ces œuvres sont hors de la mesure en base : sans contribution source pour les premières, au-delà de 200 auteurs pour les secondes.
- 24 des 47 enregistrements sources décalés ont un auteur collectif en position 0. Un quart des 96 enregistrements sources OpenAlex à auteur collectif en position 0 sont décalés.
- Dans d'autres, le décalage commence à un auteur collectif placé plus loin : « MacaqueNet » en position 2 de W4407421416.
- Les noms restent alignés (`noms_decales.py`) : dans les 47 enregistrements sources décalés, `raw_author_name` concorde avec `author.display_name` de la même position pour les 1 341 contributions.
- Sens d'après les adresses WoS des mêmes auteurs (`sens.py`) : auteur inséré pour 23 des 47 enregistrements sources décalés, auteur manquant pour 9, sens mixte pour 5. Les 10 autres sont sans enregistrement WoS ou sans auteur comparable.
- 22 des 23 enregistrements sources à auteur inséré contiennent un auteur collectif reconnu. 8 des 9 à auteur manquant n'en contiennent aucun, et 4 de ces 9 ont des affiliations numérotées.
- Signaux du sens tirés des seules données d'OpenAlex (`sens_interne.py`), sur les 32 enregistrements sources de sens établi : la présence d'un auteur collectif donne le sens de 30 ; une affiliation propre au premier ou au dernier auteur de la suite décalée, celui de 19.
- Auteurs collectifs mal reconnus (`noms_collectifs.py`, `collectifs_effet.sql`). Parmi les enregistrements sources décalés, seul W4407421416 contenait un collectif ignoré de `is_collective_name` (« MacaqueNet »). Mots ajoutés : « scientists », « expedition », « participants », « project », « cohort », sigles d'organismes (INRAE, CIRAD, CNRS, INSERM, OECD), locutions « advisory board » et « panel on », mot à capitale interne terminé par « Net » (MacaqueNet, WellBeNet). Ils rendent collectives 137 contributions sources, 95 d'OpenAlex et 42 de ScanR, dont 16 rattachées à une personne. « portal », « panel » et « board » seuls sont aussi des noms de famille.
- 46 contributions sources sont du périmètre par la seule adresse d'une voisine, dans 38 enregistrements sources décalés. Le sens retenu : auteur inséré avec un auteur collectif, auteur manquant sinon.
- Les enregistrements sources à toutes les adresses pour chacun contiennent 165 contributions sources du périmètre, légitimes ou non.

## Décisions

- Les adresses décalées se corrigent : chaque contribution source garde sa seule adresse.
- La détection et le sens du décalage s'appuient sur les seules données d'OpenAlex. WoS, source sans moissonnage, sert seulement à évaluer les mesures.
- Le défaut est signalé à OpenAlex, avec la méthode de correction.

## Phasage

### Phase 1 — Détection

- [x] Sens du décalage d'après WoS.
- [x] Signaux du sens tirés des seules données d'OpenAlex.
- [x] Reconnaissance des auteurs collectifs : mots, locutions et noms de réseau ajoutés à `is_collective_name`.
- [ ] Règle du domaine : détection et sens du décalage sur les adresses brutes d'un enregistrement source, par position.
- [ ] Revue des enregistrements sources de sens mixte ou sans enregistrement WoS, et des enregistrements sources de score 0,5 à 0,8.

### Phase 2 — Correction à la normalisation d'OpenAlex

- [ ] Adresses brutes : chaque contribution source garde sa seule adresse, selon le sens du décalage ; l'auteur inséré n'en garde aucune.
- [ ] Institutions et ROR : même correction.
- [ ] Effet sur le stock : contributions sources et publications qui sortent du périmètre.
- [ ] Reprise du stock : réhydratation des seuls enregistrements sources concernés (`rehydrate_staging_from_raw_store.py --resync-contributions`), puis normalisation. Les enregistrements sources aux contributions sources rendues collectives par `is_collective_name` en font partie. Le script sélectionne par préfixe d'identifiant ou par type de document : une sélection par liste est à ajouter.

### Phase 3 — Toutes les adresses à chacun

- [ ] Revue des 46 enregistrements sources.
- [ ] Traitement de leurs adresses.

### Phase 4 — Signalement à OpenAlex

- [ ] Ticket sur openalex.org/contact : exemples, critère, méthode de correction.

### Phase 5 — Documentation

- [ ] Mise à jour de la documentation : normalisation d'OpenAlex.

## Questions ouvertes

- Sens d'un enregistrement source décalé sans auteur collectif reconnu : auteur manquant, ou auteur collectif non reconnu.
