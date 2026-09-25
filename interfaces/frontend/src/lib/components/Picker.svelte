<script lang="ts" generics="T">
  import type { Snippet } from "svelte";
  import { autofocus } from "$lib/actions/focus";
  import { anchored } from "$lib/actions/anchored";

  let {
    search = $bindable(),
    results,
    onpick,
    onclose,
    onsearch,
    placeholder = "Rechercher…",
    emptyText = "Aucun résultat",
    loading = false,
    minLength = 0,
    floating = false,
    align = "start",
    item,
    header,
    element = $bindable(),
  }: {
    search: string;
    results: T[];
    onpick: (result: T) => void;
    onclose: () => void;
    /** Appelé à chaque saisie, pour une recherche côté serveur. */
    onsearch?: (query: string) => void;
    placeholder?: string;
    emptyText?: string;
    /** Recherche en cours : la liste affiche « Recherche… ». */
    loading?: boolean;
    /** Longueur de saisie en dessous de laquelle la liste est masquée. */
    minLength?: number;
    /** Champ compact suivi d'un bouton Annuler, et liste en panneau flottant ancré sous lui. Convient aux cellules de tableau et aux espaces étroits. */
    floating?: boolean;
    /** Alignement du panneau flottant sur le champ. */
    align?: "start" | "end";
    /** Rendu du contenu d'un résultat (la seule chose qui diffère entre pickers). */
    item: Snippet<[T]>;
    /** Contenu optionnel au-dessus du champ (raccourcis, etc.). */
    header?: Snippet;
    /** Conteneur exposé pour la détection de clic-extérieur côté parent. */
    element?: HTMLDivElement;
  } = $props();

  const showResults = $derived(search.trim().length >= minLength);

  // Le focus arrive dans la recherche (use:autofocus). La navigation entre résultats se fait au Tab natif — ce sont des boutons — et la sélection à Entrée/Espace sur le bouton focalisé. On ne gère donc au clavier qu'Échap, au niveau du conteneur (capté que le focus soit sur la recherche ou un résultat). stopPropagation : ne pas fermer un Modal englobant au passage.
  function onkeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onclose();
    }
  }
</script>

{#snippet list()}
  {#if loading}
    <div class="picker-item disabled">Recherche…</div>
  {:else if results.length === 0}
    <div class="picker-item disabled">{emptyText}</div>
  {:else}
    {#each results as result, i (i)}
      <button class="picker-item" onclick={() => onpick(result)}>
        {@render item(result)}
      </button>
    {/each}
  {/if}
{/snippet}

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="picker-container" class:floating bind:this={element} {onkeydown} onclick={(e) => e.stopPropagation()}>
  {#if header}{@render header()}{/if}
  {#if floating}
    <div class="picker-row">
      <input type="search" {placeholder} bind:value={search} oninput={() => onsearch?.(search)} use:autofocus autocomplete="off" />
      <button class="btn btn-sm" onclick={onclose}>Annuler</button>
    </div>
    {#if showResults}
      <div class="picker-results picker-panel" use:anchored={{ align, offset: 2 }}>{@render list()}</div>
    {/if}
  {:else}
    <input type="search" {placeholder} bind:value={search} oninput={() => onsearch?.(search)} use:autofocus autocomplete="off" />
    {#if showResults}
      <div class="picker-results">{@render list()}</div>
    {/if}
  {/if}
</div>

<style>
  .picker-container {
    position: relative;
    margin: 8px 0;
    background: white;
    border: 1px solid var(--accent);
    border-radius: 5px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
    max-width: 380px;
    z-index: 50;
  }
  .picker-container > input {
    width: 100%;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid var(--border);
    border-radius: 5px 5px 0 0;
    font-size: 0.95rem;
    outline: none;
    font-family: inherit;
  }
  .picker-container.floating {
    display: inline-block;
    margin: 0;
    background: none;
    border: none;
    box-shadow: none;
    max-width: none;
  }
  .picker-row {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .picker-row input {
    width: 200px;
    padding: 3px 6px;
    font-size: 0.85rem;
    border: 1px solid var(--accent);
    border-radius: 3px;
    font-family: inherit;
  }
  .picker-results {
    max-height: 200px;
    overflow-y: auto;
  }
  .picker-panel {
    z-index: 50;
    min-width: 350px;
    max-width: 600px;
    background: white;
    border: 1px solid var(--border);
    border-radius: 4px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  }
  .picker-item {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    padding: 6px 10px;
    font-size: 0.95rem;
    cursor: pointer;
    background: none;
    border: none;
    text-align: left;
    font-family: inherit;
    color: inherit;
  }
  .picker-panel .picker-item {
    display: block;
    padding: 5px 8px;
    font-size: 0.85rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .picker-item:hover {
    background: var(--accent-light);
  }
  /* Option atteinte au Tab : même fond bleu pâle que le survol (le cadre bleu par défaut est peu lisible, voire invisible quand il n'y a qu'un résultat). */
  .picker-item:focus-visible {
    background: var(--accent-light);
    outline: none;
  }
  .picker-item.disabled {
    color: var(--text-muted);
    cursor: default;
  }
</style>
