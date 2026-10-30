"""Le type JSONB du projet.

`Jsonb` écrit `None` en NULL SQL. Le type de SQLAlchemy le sérialise en JSON `null`. Python relit les deux valeurs en `None`, SQL les distingue. Une colonne mêlant les deux formes échappe aux contraintes et aux index sur NULL : un unique `NULLS NOT DISTINCT` laisse passer le doublon, un index partiel `WHERE col IS NOT NULL` indexe des lignes vides, `col IS NULL` manque une partie des lignes.

Le type s'utilise partout où une valeur JSON s'écrit : en colonne de table et en paramètre lié.
"""

from sqlalchemy.dialects.postgresql import JSONB

Jsonb = JSONB(none_as_null=True)
