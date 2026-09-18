# Chantier — Revues divergentes selon les sources

## Contexte

Les enregistrements d'une même publication portent parfois des revues différentes selon leur source. Des échantillons examinés sur une base qui n'a reçu ni les fusions (phase 4) ni les règles sur les livres (phase 6) du chantier [Revues](DATA_revues-issn-et-doublons.md) montrent cinq causes :

- **Doublon de revues.** Hors ISSN et titre communs, ce sont surtout des abréviations de titre sans espace : `Phys.Rev.Lett.`, `Eur.Phys.J.C`, `JINST`. C'est la forme des titres dans INSPIRE, la base bibliographique de la physique des hautes énergies. HAL et ScanR les portent sans ISSN ni éditeur, sur des dépôts des laboratoires de l'IN2P3. S'y ajoutent les titres successifs d'une même revue : *Progrès en Urologie* devenu *The French Journal of Urology*, *BMC Family Practice* devenu *BMC Primary Care*.
- **Livre ou chapitre.** La plateforme de l'éditeur (OpenAlex, ScanR) s'oppose au titre du livre (Crossref).
- **Titre de revue parasite.** Des copies d'articles sont déposées dans des entrepôts (DESY, GSI). Le normaliseur DataCite crée une revue à partir de leur titre de conteneur, volume compris : `Physical review / D D 99(1)`.
- **Revue erronée dans une source, ou niveau de collection différent.** *SSRN Electronic Journal* (ScanR) pour un article de *Journal of Development Economics*, *Microscopy Today* (HAL) pour un article de *Microscopy*.
- **Enregistrements réunis à tort dans une publication.** *Annals of Forest Science* et *Peer Community In Forest and Wood Sciences* (HAL, sans DOI).

Quand Crossref fournit une revue, la publication prend celle-là : Crossref passe avant toutes les autres sources qui en fournissent une.

## Décisions

- Les titres successifs d'une revue fusionnent. Le titre suivant absorbe le titre précédent : les anciens ISSN rejoignent les ISSN rejetés, les anciens titres les formes de nom. Une filiation des titres se reconstruira à partir d'eux si un besoin apparaît.
- Seule la continuation d'une revue sous un autre titre fusionne. Une scission, une fusion de deux titres ou une absorption laissent les titres distincts, chacun avec ses publications.
- Un supplément fusionne avec sa revue.
- Les ISSN rejetés gardent la seule revue et ses suppléments ; un ISSN d'une autre publication est écarté. Deux revues vérifiées qui partagent un ISSN, rejetés compris, fusionnent.
- Revue erronée dans une source : une fois écartés les doublons de revues et les enregistrements réunis à tort, Crossref fait autorité quand il donne une revue. HAL, saisi à la main, est la première source de ces erreurs.

## Phasage

### 1. Mesure

- [x] Script d'audit versionné : classement des couples (publication, revue A, revue B) par cause, échantillons.
- [ ] Mesure en production.

### 2. Titres parasites

- [x] Origine : notices DataCite qui ne décrivent pas la version publiée. Ce sont surtout des copies d'articles déposées par les entrepôts GSI, DESY et RWTH, de type `Text` : DataCite découpe mal leur `SeriesInformation`, une citation en texte libre (« Physics letters / B 777 »). S'y ajoutent des notes de version de logiciels Zenodo et des mentions de pagination (« 22 Seiten (2023). »).
- [x] Normalisation DataCite : le conteneur désigne une revue selon `container_names_a_journal` : type d'article, de communication, de recueil d'actes, de livre, de chapitre ou de data paper, sous sa forme contrôlée ou libre, et conteneur qui ne vient pas d'une citation. Le type seul ne suffit pas : à l'échelle de DataCite, les premiers déposants de `JournalArticle` sont des entrepôts (Zenodo, figshare), et des éditeurs déclarent encore `Text` (E-Periodica, Classiques Garnier).
- [ ] Stock : oneshot `backfill_detach_datacite_journals`, puis `publishers_journals` pour supprimer les revues vidées.
- [ ] Autres sources : mesure en production après le nettoyage de DataCite.

### 3. Doublons restants

- [x] Règle de fusion dans `publishers_journals` : revues que les enregistrements d'une même publication portent, sous des titres compatibles (`compatible_titles`), et qui n'ont pas chacune des ISSN sans aucun en commun. Simulation sur la base locale : 104 fusions, aucune à tort.
- [x] Titres successifs et suppléments : la vérification Sudoc range parmi les ISSN rejetés les titres précédents ou suivants de la même revue (`430`, `440`) et le supplément (`421`, `422`), liaison codée d'un côté ou de l'autre. Elle écarte les ISSN d'une autre publication : erreurs de source, titres issus d'une scission, d'une fusion ou d'une absorption. Deux revues vérifiées fusionnent quand l'une porte parmi ses ISSN rejetés un ISSN que l'autre porte dans ses colonnes ; la revue dont le document le plus récent est le plus tardif absorbe l'autre. Une migration remet toutes les revues à vérifier, pour reclasser leurs ISSN rejetés.
- [ ] Titres successifs que le Sudoc ne lie pas (*Progrès en Urologie* et *The French Journal of Urology*) : signal à trouver, ou fusion manuelle.
- [ ] Mots que l'abréviation omet (`Nucl.Instrum.Meth.A` pour *Nuclear Instruments and Methods in Physics Research Section A*) : hors de la règle, à examiner après la mesure en production.

### 4. Enregistrements réunis à tort

- [ ] Examen des cas relevés.

### 5. Revue erronée dans une source

- [x] Audit préalable (`audit_journals_against_crossref`) : écarts à Crossref par source, divergences sans Crossref, préprints DataCite.
- [ ] Correction dans `metadata_correction` : l'enregistrement dont la revue diffère de celle de l'enregistrement Crossref de même DOI prend la revue de Crossref, avec trace dans `raw_metadata`.

## Questions ouvertes

- Revue erronée sans enregistrement Crossref : quelle source fait foi ?
