<script lang="ts" generics="T">
  import type { Snippet } from "svelte";
  import { autofocus } from "#lib/actions/focus.js";
  import { anchored } from "#lib/actions/anchored.js";

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
    <div class="option-row disabled">Recherche…</div>
  {:else if results.length === 0}
    <div class="option-row disabled">{emptyText}</div>
  {:else}
    {#each results as result, i (i)}
      <button class="option-row" onclick={() => onpick(result)}>
        {@render item(result)}
      </button>
    {/each}
  {/if}
{/snippet}

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="picker-container" class:popover={!floating} class:floating bind:this={element} {onkeydown} onclick={(e) => e.stopPropagation()}>
  {#if header}{@render header()}{/if}
  {#if floating}
    <div class="picker-row">
      <input type="search" class="input-sm" {placeholder} bind:value={search} oninput={() => onsearch?.(search)} use:autofocus autocomplete="off" />
      <button class="btn btn-sm" onclick={onclose}>Annuler</button>
    </div>
    {#if showResults}
      <div class="picker-results picker-panel popover" use:anchored={{ align, offset: 2 }}>{@render list()}</div>
    {/if}
  {:else}
    <input type="search" class="panel-search input-sm" {placeholder} bind:value={search} oninput={() => onsearch?.(search)} use:autofocus autocomplete="off" />
    {#if showResults}
      <div class="picker-results">{@render list()}</div>
    {/if}
  {/if}
</div>

<style>
  .picker-container {
    position: relative;
    margin: 8px 0;
    padding-top: 4px;
    max-width: 380px;
    z-index: 50;
  }
  .picker-container.floating {
    display: inline-block;
    margin: 0;
    padding-top: 0;
    max-width: none;
  }
  .picker-row {
    display: flex;
    gap: 4px;
    align-items: center;
  }
  .picker-row input {
    width: 200px;
  }
  .picker-results {
    max-height: 200px;
    overflow-y: auto;
  }
  .picker-panel {
    min-width: 350px;
    max-width: 600px;
  }
  .picker-panel .option-row {
    display: block;
    padding: 5px 8px;
    font-size: var(--fs-sm);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .option-row.disabled {
    color: var(--muted);
    cursor: default;
  }
</style>
