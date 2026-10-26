<script lang="ts">
  /** Onglet d'un référentiel d'administration : la liste, ou une file de triage. */
  export interface HubTab {
    key: string;
    label: string;
    /** Nombre d'éléments de la file, affiché en pastille quand il est positif. */
    count?: number;
  }

  let {
    tabs,
    active,
    onselect,
  }: {
    tabs: HubTab[];
    active: string;
    onselect: (key: string) => void;
  } = $props();
</script>

<nav class="tabs hub-tabs">
  {#each tabs as t (t.key)}
    <button class="tab" class:active={active === t.key} onclick={() => onselect(t.key)}>
      {t.label}
      {#if t.count}<span class="tab-count">{t.count.toLocaleString("fr-FR")}</span>{/if}
    </button>
  {/each}
</nav>

<style>
  /* Les onglets d'une liste ouvrent la page : la marge haute des onglets de fiche, qui les sépare de l'en-tête de l'entité, est superflue. */
  .hub-tabs {
    margin-top: 0;
  }
</style>
