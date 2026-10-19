# Chantier — Vérification des affiliations des sources

## Contexte

Une signature appartient au périmètre par ses indices (`perimeter_evidence`) : adresse, structure HAL, ROR, identité RH, établissement de thèse. Chaque source donne ses indices pour sa propre signature. Une source attribue parfois à un auteur l'affiliation d'un autre auteur, ou une affiliation fausse. Une personne hors RH entrée dans le périmètre par une telle affiliation est une fausse personne du périmètre.

Le chantier [alignement des auteurs](DATA_alignement-auteurs.md) a relu les liens au périmètre établis par la seule signature scanR. Le lien était faux dans 12 cas sur 25 pour une structure, dans 10 cas sur 15 pour une adresse.

## Décisions

## Phasage

### Phase 1 — Mesure

- [x] Signatures OpenAlex du périmètre dont les adresses donnent la France et un autre pays, le 2026-10-19 (`measure_openalex_two_countries.sql`) : 11 624, dans 6 160 publications. OpenAlex réunit souvent dans une signature les affiliations de deux auteurs.
  - Autres signatures du groupe : France ou indice de périmètre dans 8 850 cas, autres pays seulement dans 1 650, aucun pays dans 1 001. OpenAlex est seul dans le groupe dans 123 cas.
  - 565 personnes hors RH ont pour seul appui au périmètre des signatures de ce type, sans confirmation. Le périmètre compte 15 024 personnes hors RH.
  - Les notices de plus de 500 auteurs contiennent 1 780 des 2 774 signatures sans confirmation. 244 des 565 personnes signent ainsi dans une notice de 10 auteurs au plus.
  - Exemple g5296946 : une université chinoise et un laboratoire du périmètre. La signature HAL du dépôt in2p3, de 54 auteurs, donne aussi ce laboratoire.
  - Relecture de 65 de ces 565 personnes, le 2026-10-19 (`build_multicountry_review.py`) : 57 fausses personnes du périmètre, 3 doubles affiliations réelles, 5 cas indéterminables. Par plus petite notice concernée : 18 fausses sur 25 jusqu'à 10 auteurs, 19 sur 20 de 11 à 500 auteurs, 20 sur 20 au-delà. L'adresse française appartient à un autre auteur, ou l'adresse est fausse.
- [ ] Personnes hors RH dont aucune signature du périmètre n'est confirmée par une autre source de son groupe, par source et type d'indice.
- [ ] Échantillon de ces personnes relu à la main, par source et type d'indice.

### Phase 2 — INSPIRE-HEP

- [ ] Couverture d'INSPIRE-HEP sur les publications de physique des hautes énergies du stock, selon le nombre d'auteurs.
- [ ] Affiliations d'INSPIRE-HEP confrontées à celles d'OpenAlex, de HAL et de scanR, sur les signatures du périmètre.

### Phase 3 — Règles

- [ ] Règles de confirmation des indices de périmètre, choisies d'après les phases 1 et 2.

### Phase 4 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Une adresse OpenAlex à plusieurs pays, que les autres sources du groupe ne confirment pas, cesse-t-elle d'être un indice de périmètre ? Sur les 60 cas jugés de la relecture du 2026-10-19, la règle perd 3 doubles affiliations réelles.
- Les affiliations décalées ou fausses qui ne donnent pas plusieurs pays.
