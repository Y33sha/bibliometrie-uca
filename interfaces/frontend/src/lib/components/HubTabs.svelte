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

<nav class="hub-tabs">
  {#each tabs as t (t.key)}
    <button class="hub-tab" class:active={active === t.key} onclick={() => onselect(t.key)}>
      {t.label}
      {#if t.count}<span class="tab-badge">{t.count}</span>{/if}
    </button>
  {/each}
</nav>

<style>
  .hub-tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--border, #e0e0e0);
    margin-bottom: 14px;
  }
  .hub-tab {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 14px;
    cursor: pointer;
    font: inherit;
    color: #666;
    display: inline-flex;
    align-items: center;
    gap: 6px;
  }
  .hub-tab:hover {
    color: #222;
  }
  .hub-tab.active {
    color: var(--accent, #1976d2);
    border-bottom-color: var(--accent, #1976d2);
    font-weight: 600;
  }
  .tab-badge {
    background: var(--accent, #1976d2);
    color: white;
    border-radius: 10px;
    font-size: 0.72rem;
    padding: 0 7px;
    font-weight: 600;
  }
</style>
