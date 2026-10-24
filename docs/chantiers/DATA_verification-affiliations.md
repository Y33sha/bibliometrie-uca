# Chantier — Vérification des affiliations des sources

## Contexte

Une contribution source appartient au périmètre par ses indices (`perimeter_evidence`) : adresse, structure HAL, ROR, fiche RH, établissement de thèse. Chaque source donne ses indices pour sa propre contribution source. Une source attribue parfois à un auteur l'affiliation d'un autre auteur, ou une affiliation fausse. Une personne hors RH entrée dans le périmètre par une telle affiliation est une fausse personne du périmètre.

Le chantier [alignement des auteurs](archived/2026-10-24_DATA_alignement-auteurs.md) a relu les liens au périmètre établis par la seule contribution source scanR. Le lien était faux dans 12 cas sur 25 pour une structure, dans 10 cas sur 15 pour une adresse.

## Décisions

- Un groupe dont certaines contributions sources donnent un indice de périmètre et d'autres une affiliation hors périmètre est un cas conflictuel. Une file d'administration le présente pour décision.

## Phasage

### Phase 1 — Mesure

- [x] Contributions sources OpenAlex du périmètre dont les adresses donnent la France et un autre pays, le 2026-10-19 (`measure_openalex_two_countries.sql`) : 11 624, dans 6 160 publications. OpenAlex réunit souvent dans une contribution source les affiliations de deux auteurs.
  - Autres contributions sources du groupe : France ou indice de périmètre dans 8 850 cas, autres pays seulement dans 1 650, aucun pays dans 1 001. OpenAlex est seul dans le groupe dans 123 cas.
  - 565 personnes hors RH ont pour seul appui au périmètre des contributions sources de ce type, sans confirmation. Le périmètre compte 15 024 personnes hors RH.
  - Les enregistrements sources de plus de 500 auteurs contiennent 1 780 des 2 774 contributions sources sans confirmation. 244 des 565 personnes signent ainsi dans un enregistrement source de 10 auteurs au plus.
  - Exemple g5296946 : une université chinoise et un laboratoire du périmètre. La contribution source HAL du dépôt in2p3, de 54 auteurs, donne aussi ce laboratoire.
  - Relecture de 65 de ces 565 personnes, le 2026-10-19 (`build_multicountry_review.py`) : 57 fausses personnes du périmètre, 3 doubles affiliations réelles, 5 cas indéterminables. Par plus petit enregistrement source concerné : 18 fausses sur 25 jusqu'à 10 auteurs, 19 sur 20 de 11 à 500 auteurs, 20 sur 20 au-delà. L'adresse française appartient à un autre auteur, ou l'adresse est fausse.
- [x] Personnes hors RH dont aucune contribution source du périmètre n'est confirmée par une autre source de son groupe, le 2026-10-19 (`measure_unconfirmed_perimeter.sql`) : 5 794 sur 15 024. Une contribution source est confirmée quand une contribution source d'une autre source du même groupe est aussi du périmètre.

  | Source des indices | Personnes | Dont autre affiliation dans une autre source |
  |---|---|---|
  | OpenAlex | 3 429 | 1 636 |
  | plusieurs sources | 649 | 413 |
  | WoS | 639 | 523 |
  | HAL | 539 | 304 |
  | theses.fr | 348 | 1 |
  | scanR | 182 | 135 |
  | Crossref, DataCite | 8 | 5 |

  - 991 de ces personnes ont une contribution source OpenAlex aux adresses de la France et d'un autre pays.
- [x] Échantillon de 70 de ces personnes relu à la main, hors adresses OpenAlex à plusieurs pays, le 2026-10-19 (`build_perimeter_review.py`).

  | Source des indices | Autres sources | Relues | Fausses | Justes | Indéterminables |
  |---|---|---|---|---|---|
  | OpenAlex | autre affiliation | 12 | 12 | 0 | 0 |
  | OpenAlex | aucune affiliation | 10 | 2 | 2 | 6 |
  | HAL | autre affiliation | 8 | 6 | 2 | 0 |
  | HAL | aucune affiliation | 8 | 0 | 0 | 8 |
  | WoS | autre affiliation | 8 | 4 | 4 | 0 |
  | scanR | toutes | 8 | 7 | 0 | 1 |
  | plusieurs sources | autre affiliation | 6 | 4 | 2 | 0 |
  | plusieurs sources | aucune affiliation | 4 | 0 | 4 | 0 |
  | theses.fr | aucune affiliation | 6 | 0 | 6 | 0 |

  - Une thèse en préparation a pour seul enregistrement source celui de theses.fr. Ses indices sont justes, mais aucune autre source ne peut les confirmer.
  - HAL seul : surtout des publications antérieures à 2017, d'auteurs partis depuis longtemps.
  - WoS se trompe sur la ville d'une adresse de l'université Côte d'Azur, dont le sigle est aussi UCA.
  - Cas limites de périmètre : CHU, laboratoire homonyme d'une autre ville.

### Phase 2 — INSPIRE-HEP

- [ ] Couverture d'INSPIRE-HEP sur les publications de physique des hautes énergies du stock, selon le nombre d'auteurs.
- [ ] Affiliations d'INSPIRE-HEP confrontées à celles d'OpenAlex, de HAL et de scanR, sur les contributions sources du périmètre.

### Phase 3 — Règles

- [ ] Règles de confirmation des indices de périmètre, choisies d'après les phases 1 et 2.
- [ ] File d'administration des groupes aux affiliations conflictuelles. Elle dépend du chantier [résolution des personnes par groupe](archived/2026-10-24_DATA_resolution-personnes.md).

### Phase 4 — Fin de chantier

- [ ] Mise à jour de la documentation.

## Questions ouvertes

- Une adresse OpenAlex à plusieurs pays, que les autres sources du groupe ne confirment pas, cesse-t-elle d'être un indice de périmètre ? Sur les 60 cas jugés de la relecture du 2026-10-19, la règle perd 3 doubles affiliations réelles.
- Les affiliations décalées ou fausses qui ne donnent pas plusieurs pays.
