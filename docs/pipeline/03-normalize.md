#  Normalisation

*À jour le 2026-09-06.*

```mermaid
flowchart LR
    B[staging]-->|normalize_*|G
    subgraph G[tables sources]
        direction TB
        C[source_publications]---D[source_authorships]
    end
    C---journals---publishers
    D---|source_authorship_addresses|F[addresses]
    classDef new  fill:#bbf
    class C,D,F,journals,publishers new;
```

Phase `normalize` : transforme les données brutes (`staging`) en tables structurées propres à chaque source — `source_publications` et `source_authorships`. Peuple au passage les référentiels `publishers` et `journals`, et crée les `addresses` ainsi que les liens `source_authorship_addresses` qui rattachent une signature d'auteur à ses adresses.

Chaque normaliseur reporte dans `source_authorships` ce que sa source fournit pour chaque signature : identifiants de l'auteur (ORCID, IdRef…) et affiliations.

Conservés en base, les payloads bruts la font grossir hors de proportion avec les données normalisées qu'on en tire. En fin de phase, le `raw_data` du staging est donc vidé, puis un `VACUUM` récupère l'espace.

## Archivage du payload brut

Avant de vider `raw_data`, la normalisation dépose le payload hors base, dans le [raw store](../../infrastructure/raw_store/) : un fichier `data/raw_store/{source}/{source_id}.json.gz` par document. L'option `--no-raw-store` désactive cet archivage : le payload est alors perdu à la vidange.

Le script `interfaces/cli/maintenance/rehydrate_staging_from_raw_store.py` réinjecte les payloads d'une source, pour rejouer sa normalisation.
