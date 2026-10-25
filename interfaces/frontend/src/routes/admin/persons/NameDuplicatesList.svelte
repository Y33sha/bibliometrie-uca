<script lang="ts">
  import PersonPairsList from "./PersonPairsList.svelte";
  import type { components } from "#lib/api/schema.js";

  type Pair = components["schemas"]["NameDuplicatePairOut"];

  let {
    onopenPerson,
    onchange,
    reloadKey,
  }: {
    onopenPerson: (personId: number) => void;
    onchange: () => void;
    reloadKey: number;
  } = $props();

  const OVERLAPS: [keyof Pair["overlaps"], string][] = [
    ["coauthors", "co-auteurs"],
    ["shared_publications", "publis communes"],
    ["labs", "labos"],
    ["serials", "publications en série"],
  ];
</script>

<PersonPairsList
  endpoint="/api/persons/name-duplicates"
  apiKey="name-duplicates"
  emptyText="Aucune paire candidate par nom."
  distinctTitle="Personnes distinctes (homonymes)"
  {onopenPerson}
  {onchange}
  {reloadKey}
>
  {#snippet intro()}
    Paires de personnes aux <strong>noms compatibles</strong>, triées par recouvrement de réseau. Un
    réseau commun (co-auteurs, publications co-signées) signe un <em>doublon</em> à fusionner ; des
    réseaux disjoints signent un <em>homonyme</em> légitime, à marquer distinct.
  {/snippet}
  {#snippet pairHeader(pair: Pair)}
    <div class="overlaps">
      {#each OVERLAPS as [key, label] (key)}
        <span class="ov" class:zero={pair.overlaps[key] === 0}>
          <span class="ov-n">{pair.overlaps[key]}</span>{label}
        </span>
      {/each}
    </div>
  {/snippet}
</PersonPairsList>

<style>
  .overlaps {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 0.8rem;
    margin-bottom: 8px;
  }
  .ov {
    color: var(--text);
  }
  .ov.zero {
    color: var(--unknown);
  }
  .ov-n {
    font-weight: 700;
    margin-right: 3px;
  }
</style>
