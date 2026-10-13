# Chantier — Licences des publications

## Contexte

Le chantier moissonne la licence de chaque publication : CC BY, CC BY-NC-ND, licence éditeur, aucune.

### Champs par source

Mesure du 2026-10-02, sur la base entière (Crossref, DataCite) ou sur les payloads bruts (OpenAlex, scanR).

| Source | Champ | Granularité | Stockage | Couverture |
| --- | --- | --- | --- | --- |
| Crossref | `license[]` : URL, `content-version`, date de début, délai | version du texte | `source_publications.meta->'license'` | 26 097 enregistrements sur 36 392 |
| DataCite | `rights[]` : libellé, URI, identifiant SPDX | enregistrement | `source_publications.meta->'rights'` | 8 058 enregistrements sur 14 965 |
| OpenAlex | `locations[].license`, avec `version` et type de la source | location | payload brut | 45 169 travaux sur 99 024 |
| Unpaywall | `oa_locations[].license`, avec `host_type` et `version` | location | non interrogé pour la licence | — |
| scanR | `oaEvidence.license`, avec `hostType` et `version` | meilleure location | payload brut, lu pour dériver `oa_status` | 23 286 enregistrements sur 60 683 |
| HAL | `licence_s` | fichier déposé | non extrait | — |

Le Web of Science et theses.fr ne donnent aucune licence.

### Vocabulaires

- **Crossref.** URL libres, 188 distinctes. Les licences Creative Commons ont 61 formes, 36 après normalisation du schéma, du `www` et de la barre finale. Les licences éditeur sont des URL propres à chaque éditeur (Wiley, Springer, Elsevier, OUP…). Versions : `vor` (14 790 enregistrements), `tdm` (fouille de texte, 14 304), `unspecified` (4 096), `stm-asf` (2 715), `am` (manuscrit accepté, 2 121). 1 970 licences `am` sur 2 124 ont un délai : c'est l'embargo.
- **DataCite.** Identifiant SPDX (`cc-by-4.0`, `cc0-1.0`, `mit`) le plus souvent, absent sur 3 413 entrées, en casse et forme variables (`cc by 4.0`, `CC-BY-4.0`). Le champ `rightsUri` porte aussi des droits d'accès (`info:eu-repo/semantics/openAccess`, COAR) et les licences arXiv (`nonexclusive-distrib`, 1 406). Les logiciels portent des licences logicielles (MIT, GPL, CeCILL).
- **OpenAlex et Unpaywall.** Vocabulaire fermé, sans numéro de version de la licence : `cc-by`, `cc-by-sa`, `cc-by-nc`, `cc-by-nd`, `cc-by-nc-sa`, `cc-by-nc-nd`, `public-domain`, `other-oa`, `publisher-specific-oa`, `mit`.
- **scanR.** Mélange le vocabulaire OpenAlex et des URL : Creative Commons, licences HAL, licence ouverte Etalab.
- **HAL.** URL : Creative Commons, `hal-authorisation-v1`, `licences/copyright`. Présente seulement quand un fichier est déposé.

### Cohérence entre sources

Échantillon de 500 publications du périmètre, parues depuis 2018, présentes dans HAL, Crossref et OpenAlex. 83 sont sans licence dans toutes les sources.

| Comparaison | Accord | Écarts |
| --- | --- | --- |
| OpenAlex (location principale) et Unpaywall (location éditeur) | 231 sur 231 | — |
| Crossref (`vor`) et OpenAlex (location principale) | 160 sur 164 | vocabulaire : URL éditeur pour `other-oa`, CC0 pour `public-domain` ; 1 désaccord réel (CC BY contre CC BY-NC-ND) |
| HAL et Crossref (`vor`) | 67 sur 131 | `hal-authorisation` face à une licence éditeur CC BY (17) ou propre à l'éditeur (20) ; variante CC différente (11) |
| HAL et OpenAlex (location dépôt) | 139 sur 215 | OpenAlex rend `hal-authorisation` par `other-oa` (38) |
| scanR et les autres sources | 204 sur 232 | — |

La licence HAL porte sur le fichier déposé. Elle peut différer de la licence de la version éditeur.

### Licence `other-oa` d'OpenAlex

Mesure du 2026-10-13 sur le raw store. 6 295 travaux ont la licence `other-oa` en localisation principale. Cette localisation est une archive : HAL (3 447), theses.fr (1 319), Zenodo (395). 548 de ces travaux sont dans Crossref, dont 367 sans licence de la version éditeur.

## Décisions

- **Vocabulaire fermé**, enum du domaine :
  - `cc-by`, `cc-by-sa`, `cc-by-nd`, `cc-by-nc`, `cc-by-nc-sa`, `cc-by-nc-nd`, sans numéro de version ;
  - `public-domain` : CC0, Public Domain Mark, `public-domain` d'OpenAlex ;
  - `licence-ouverte` : Licence Ouverte Etalab, toutes versions ;
  - `open-source` : licences de logiciel libre (MIT, BSD, GPL, LGPL, Apache, CeCILL, AFL) ;
  - `repository-distribution` : autorisation de diffusion HAL, licence non exclusive arXiv ;
  - `publisher-open` : `publisher-specific-oa` d'OpenAlex et de scanR ;
  - `other-oa` : `other-oa` d'OpenAlex ;
  - `all-rights-reserved` : copyright HAL, `rightsstatements.org` InC, `reserved` ;
  - `other` : politiques de données, formes non classées.
- **Normalisation** : une règle du domaine ramène une forme brute (URL, identifiant SPDX, code OpenAlex) à l'enum. L'URL d'une licence d'éditeur dans Crossref reste sans valeur normalisée. Les droits d'accès (COAR, `info:eu-repo`) et les licences de fouille de texte (`tdm`, `stm-asf`) sont écartés.
- **Stockage** : type PostgreSQL `license_type`, reflet de l'enum.
  - `source_publications.license` : licence normalisée de la notice, calculée à la normalisation. La forme brute reste dans `meta`. Crossref : `vor`, sinon `unspecified`. DataCite : identifiant SPDX, sinon URI. OpenAlex : localisation principale seule. HAL : fichier déposé.
  - `publications.license` : licence de la version éditeur, arbitrée entre les sources.
  - `publications.deposit_license` : licence du fichier déposé dans HAL.
- **Arbitrage** de la licence de la version éditeur : Crossref (`vor`), puis OpenAlex (localisation éditeur), puis scanR. DataCite pour les jeux de données.
- **HAL** : `licence_s` extrait dans `source_publications.meta`, clé `licence`.

## Phasage

### Phase 1 — Inventaire

- [x] Champs de licence de chaque source, dont Unpaywall et Web of Science
- [x] Vocabulaire de chaque source : URL, codes, libellés
- [x] Cohérence entre sources sur les publications communes
- [ ] Licence par version du texte : publiée, acceptée, preprint

### Phase 2 — Modèle

- [x] Extraction de `licence_s` dans HAL
- [x] Inventaire des formes de OpenAlex, scanR, Crossref et DataCite
- [ ] Inventaire des formes de HAL, après un moissonnage complet. Échantillon de 1 223 notices : 10 formes, toutes reconnues.
- [x] Enum du domaine et règle de normalisation, testée sur les formes de l'inventaire : `domain/publications/licenses.py`
- [ ] Emplacement du stockage : migration
- [ ] Licences OpenAlex et scanR extraites à la normalisation ; stock rejoué depuis le raw store
- [ ] Règle d'arbitrage entre sources

### Phase 3 — Fin de chantier

- [ ] Mise à jour de la documentation

## Questions ouvertes

- Licence de la version déposée dans HAL face à la licence de l'éditeur.
