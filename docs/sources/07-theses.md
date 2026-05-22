# Theses.fr

*À documenter sur le même modèle (API utilisées, données récupérées, particularités).*

Extracteur dans [infrastructure/sources/theses/](https://github.com/Y33sha/bibliometrie-uca/tree/master/infrastructure/sources/theses),
normaliseur dans [application/pipeline/normalize/normalize_theses.py](https://github.com/Y33sha/bibliometrie-uca/blob/master/application/pipeline/normalize/normalize_theses.py).

Particularité connue : couvre thèses soutenues + en cours ; jurys et
rapporteurs matérialisés comme `source_authorships` (avec leurs `roles`)
— PPN éventuel porté par `person_identifiers->>'idref'`.
