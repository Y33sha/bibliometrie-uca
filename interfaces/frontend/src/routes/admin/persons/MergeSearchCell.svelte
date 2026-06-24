<script lang="ts">
  import { autofocus } from "$lib/actions/focus";
  import type { PersonSearchResult } from "./types";

  let {
    targetPersonId,
    active,
    mergeSearch,
    onopen,
    onclose,
    onmerge,
  }: {
    targetPersonId: number;
    /** `true` quand la recherche est ouverte pour cette personne. */
    active: boolean;
    /** Composable `useDebouncedSearch` partagé par toutes les lignes. */
    mergeSearch: {
      query: string;
      loading: boolean;
      results: PersonSearchResult[];
      setQuery: (q: string) => void;
    };
    onopen: (personId: number) => void;
    onclose: () => void;
    onmerge: (targetId: number, sourceId: number) => void | Promise<void>;
  } = $props();
</script>

{#if active}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="merge-search"
    onkeydown={(e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        onclose();
      }
    }}
  >
    <div class="merge-input-row">
      <input
        type="search"
        placeholder="Nom à absorber…"
        value={mergeSearch.query}
        use:autofocus
        oninput={(e) => mergeSearch.setQuery((e.target as HTMLInputElement).value)}
      />
      <button class="btn" onclick={onclose}>&times;</button>
    </div>
    {#if mergeSearch.loading}
      <div class="merge-results"><span class="loading-text">Recherche…</span></div>
    {:else if mergeSearch.results.length}
      <div class="merge-results">
        {#each mergeSearch.results as r (r.id)}
          <button class="merge-result" onclick={() => onmerge(targetPersonId, r.id)}>
            <strong>{r.last_name}</strong>
            {r.first_name}
            {#if r.department_name}<span class="merge-dept">{r.department_name}</span>{/if}
            {#if r.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
          </button>
        {/each}
      </div>
    {:else if mergeSearch.query.trim().length >= 2}
      <div class="merge-results"><span class="loading-text">Aucun résultat</span></div>
    {/if}
  </div>
{:else}
  <button class="btn btn-merge-inline" onclick={() => onopen(targetPersonId)}
    >Fusionner…</button
  >
{/if}

<style>
  .btn-merge-inline {
    padding: 2px 8px;
    border: 1px dashed var(--border);
    border-radius: 4px;
    background: none;
    font-size: 0.8rem;
    cursor: pointer;
    color: var(--text-muted);
    margin-top: 4px;
    font-family: inherit;
  }
  .btn-merge-inline:hover {
    background: var(--warning-light);
    color: var(--warning);
    border-color: var(--warning);
  }
  .merge-search {
    margin-top: 4px;
    position: relative;
  }
  .merge-input-row {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .merge-input-row input {
    padding: 3px 6px;
    border: 1px solid var(--warning);
    border-radius: 3px;
    font-size: 0.85rem;
    font-family: inherit;
    width: 220px;
  }
  .merge-results {
    position: absolute;
    top: 100%;
    left: 0;
    z-index: 10;
    background: white;
    border: 1px solid var(--border);
    border-radius: 4px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
    min-width: 280px;
    max-height: 200px;
    overflow-y: auto;
    padding: 4px 0;
  }
  .merge-result {
    display: block;
    width: 100%;
    text-align: left;
    padding: 6px 10px;
    border: none;
    background: none;
    cursor: pointer;
    font-size: 0.85rem;
    font-family: inherit;
  }
  .merge-result:hover,
  .merge-result:focus-visible {
    background: var(--accent-light);
    outline: none;
  }
  .merge-dept {
    font-size: 0.8rem;
    color: var(--text-muted);
    margin-left: 6px;
  }
  .loading-text {
    color: var(--text-muted);
  }
</style>
