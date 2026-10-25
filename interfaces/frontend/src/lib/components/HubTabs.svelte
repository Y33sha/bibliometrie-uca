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

<nav class="tabs">
  {#each tabs as t (t.key)}
    <button class="tab" class:active={active === t.key} onclick={() => onselect(t.key)}>
      {t.label}
      {#if t.count}<span class="tab-count">{t.count.toLocaleString("fr-FR")}</span>{/if}
    </button>
  {/each}
</nav>
