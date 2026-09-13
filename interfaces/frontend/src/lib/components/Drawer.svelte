<script lang="ts">
  // Volet droit des référentiels de l'administration : il se ferme par Échap, par le fond et par son bouton.
  import type { Snippet } from "svelte";

  let {
    width = "480px",
    onclose,
    onescape,
    head,
    children,
  }: {
    /** Largeur du volet, plafonnée à 92 % de la fenêtre. */
    width?: string;
    onclose: () => void;
    /** Réponse à la touche Échap : fermeture du volet par défaut. */
    onescape?: () => void;
    /** Contenu de l'en-tête, à gauche du bouton de fermeture. */
    head: Snippet;
    children: Snippet;
  } = $props();

  function onkeydown(e: KeyboardEvent) {
    if (e.key === "Escape") (onescape ?? onclose)();
  }
</script>

<svelte:window {onkeydown} />

<button class="drawer-backdrop" aria-label="Fermer le panneau" onclick={onclose}></button>

<aside class="drawer" style:width={`min(${width}, 92vw)`}>
  <header class="drawer-head">
    <div class="drawer-head-content">{@render head()}</div>
    <button class="drawer-close" title="Fermer" aria-label="Fermer" onclick={onclose}>&times;</button>
  </header>
  <div class="drawer-body">{@render children()}</div>
</aside>

<style>
  .drawer-backdrop {
    position: fixed;
    top: var(--header-height, 46px);
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.25);
    border: none;
    padding: 0;
    cursor: pointer;
    z-index: 90;
  }
  .drawer {
    position: fixed;
    top: var(--header-height, 46px);
    right: 0;
    height: calc(100vh - var(--header-height, 46px));
    background: #fff;
    box-shadow: -4px 0 16px rgba(0, 0, 0, 0.15);
    z-index: 91;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .drawer-head {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 16px 18px;
    border-bottom: 1px solid var(--border, #e0e0e0);
  }
  .drawer-head-content {
    flex: 1;
    min-width: 0;
  }
  .drawer-close {
    background: none;
    border: none;
    font-size: 1.5rem;
    line-height: 1;
    cursor: pointer;
    color: #888;
    padding: 0 4px;
  }
  .drawer-close:hover {
    color: #333;
  }
  .drawer-body {
    flex: 1;
    overflow-y: auto;
    padding: 16px 18px;
  }
</style>
