<script lang="ts">
  import PersonPairsList from "./PersonPairsList.svelte";
  import type { components } from "#lib/api/schema.js";

  type Pair = components["schemas"]["IdentifierConflictPairOut"];

  let {
    onopenPerson,
    onchange,
    reloadKey,
  }: {
    onopenPerson: (personId: number) => void;
    onchange: () => void;
    reloadKey: number;
  } = $props();
</script>

<PersonPairsList
  endpoint="/api/persons/identifier-conflicts"
  apiKey="identifier-conflicts"
  emptyText="Aucune paire en conflit d'identifiant."
  distinctTitle="Personnes distinctes (identifiant mal attribué)"
  {onopenPerson}
  {onchange}
  {reloadKey}
>
  {#snippet intro()}
    Paires de personnes portant la <strong>même valeur d'identifiant</strong> (ORCID, IdRef, hal_person_id, idHAL). Mêmes nom et réseau (labos, publications) ⇒ <em>doublon</em> à fusionner ; personnes
    manifestement distinctes ⇒ <em>erreur d'attribution</em> de l'identifiant, à laisser (marquer distinctes).
  {/snippet}
  {#snippet pairHeader(pair: Pair)}
    <div class="shared-row">
      {#each pair.shared_identifiers as s (s.id_type + s.id_value)}
        <span class="ident-chip"><span class="it">{s.id_type}</span>{s.id_value}</span>
      {/each}
    </div>
  {/snippet}
</PersonPairsList>

<style>
  .shared-row {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 8px;
  }
  .ident-chip {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    font-size: 0.8rem;
    background: #eef4f5;
    border: 1px solid #cfe0e3;
    border-radius: 4px;
    padding: 1px 7px;
    font-family: var(--mono);
  }
  .ident-chip .it {
    text-transform: uppercase;
    font-size: 0.65rem;
    font-weight: 700;
    color: #15616d;
  }
</style>
