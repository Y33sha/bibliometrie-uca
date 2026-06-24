<script lang="ts" generics="T">
  import type { Snippet } from "svelte";
  import { autofocus } from "$lib/actions/focus";

  let {
    search = $bindable(),
    results,
    onpick,
    onclose,
    placeholder = "Rechercher…",
    emptyText = "Aucun résultat",
    item,
    header,
    element = $bindable(),
  }: {
    search: string;
    results: T[];
    onpick: (result: T) => void;
    onclose: () => void;
    placeholder?: string;
    emptyText?: string;
    /** Rendu du contenu d'un résultat (la seule chose qui diffère entre pickers). */
    item: Snippet<[T]>;
    /** Contenu optionnel au-dessus du champ (raccourcis, etc.). */
    header?: Snippet;
    /** Conteneur exposé pour la détection de clic-extérieur côté parent. */
    element?: HTMLDivElement;
  } = $props();

  // Le focus arrive dans la recherche (use:autofocus). La navigation entre
  // résultats se fait au Tab natif — ce sont des boutons — et la sélection à
  // Entrée/Espace sur le bouton focalisé. On ne gère donc au clavier qu'Échap,
  // au niveau du conteneur (capté que le focus soit sur la recherche ou un
  // résultat). stopPropagation : ne pas fermer un Modal englobant au passage.
  function onkeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onclose();
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="picker-container" bind:this={element} {onkeydown} onclick={(e) => e.stopPropagation()}>
  {#if header}{@render header()}{/if}
  <input type="search" {placeholder} bind:value={search} use:autofocus autocomplete="off" />
  <div class="picker-results">
    {#if results.length === 0}
      <div class="picker-item disabled">{emptyText}</div>
    {:else}
      {#each results as result, i (i)}
        <button class="picker-item" onclick={() => onpick(result)}>
          {@render item(result)}
        </button>
      {/each}
    {/if}
  </div>
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
  .picker-container input {
    width: 100%;
    padding: 7px 10px;
    border: none;
    border-bottom: 1px solid var(--border);
    border-radius: 5px 5px 0 0;
    font-size: 0.95rem;
    outline: none;
    font-family: inherit;
  }
  .picker-results {
    max-height: 200px;
    overflow-y: auto;
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
  .picker-item:hover {
    background: var(--accent-light);
  }
  /* Option atteinte au Tab : même fond bleu pâle que le survol (le cadre bleu
     par défaut est peu lisible, voire invisible quand il n'y a qu'un résultat). */
  .picker-item:focus-visible {
    background: var(--accent-light);
    outline: none;
  }
  .picker-item.disabled {
    color: var(--text-muted);
    cursor: default;
  }
</style>
