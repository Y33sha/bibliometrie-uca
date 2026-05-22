# `enrich` : Enrichissements optionnels

Exécutée uniquement en mode `full` :

| Script | Rôle |
|--------|------|
| `interfaces/cli/pipeline/enrich_oa_status.py` | Statut *open access* via API [Unpaywall](../glossaire#unpaywall) => souvent plus à jour que le statut renseigné dans les sources |
| `interfaces/cli/pipeline/enrich_journal_apc.py` | Montant APC par revue via API OpenAlex Sources => **ne sert à rien pour l'instant**, voir si on garde ou pas |
