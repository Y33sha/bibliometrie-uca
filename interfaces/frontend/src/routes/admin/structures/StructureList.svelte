<script lang="ts">
  import type { Structure } from "./types";

  let {
    structures,
    selectedId,
    search = $bindable(),
    typeFilter = $bindable(),
    onsearch,
    ontypechange,
    onselect,
    oncreate,
  }: {
    structures: Structure[];
    selectedId: number | null;
    search: string;
    typeFilter: string;
    onsearch: () => void;
    ontypechange: () => void | Promise<void>;
    onselect: (id: number) => void | Promise<void>;
    oncreate: () => void;
  } = $props();
</script>

<div class="list-panel">
  <div class="toolbar">
    <input type="text" placeholder="Rechercher..." bind:value={search} oninput={onsearch} />
    <select bind:value={typeFilter} onchange={ontypechange}>
      <option value="">Tous types</option>
      <option value="labo">Laboratoires</option>
      <option value="universite">Universités</option>
      <option value="onr">ONR</option>
      <option value="chu">CHU</option>
      <option value="ecole">Écoles</option>
      <option value="site">Sites</option>
    </select>
  </div>
  <div class="list-header">
    <span class="list-count">{structures.length} structures</span>
    <button class="btn btn-primary btn-sm" onclick={oncreate}>+ Nouvelle</button>
  </div>
  <div class="panel struct-list">
    {#if structures.length === 0}
      <div class="empty-list">Aucune structure</div>
    {:else}
      {#each structures as s (s.id)}
        <button
          class="struct-item"
          class:active={s.id === selectedId}
          onclick={() => onselect(s.id)}
        >
          <span class="type-badge type-{s.type}">{s.type}</span>
          <div class="info">
            <div class="name">
              {#if s.acronym}<strong>{s.acronym}</strong> · {s.name}{:else}{s.name}{/if}
            </div>
          </div>
        </button>
      {/each}
    {/if}
  </div>
</div>

<style>
  .list-panel {
    width: 550px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 16px;
    border-right: 1px solid var(--border);
    background: #fafaf8;
  }
  .panel {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px;
  }
  .toolbar {
    display: flex;
    gap: 6px;
    margin-bottom: 8px;
  }
  .toolbar input,
  .toolbar select {
    padding: 5px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.95rem;
    background: white;
    font-family: inherit;
  }
  .toolbar input {
    flex: 1;
  }
  .list-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 4px;
  }
  .list-count {
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  .struct-list {
    overflow-y: auto;
    max-height: calc(100vh - 240px);
    padding: 0;
  }
  .empty-list {
    padding: 20px;
    text-align: center;
    color: var(--text-muted);
  }
  .struct-item {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #f0efec;
    cursor: pointer;
    background: none;
    text-align: left;
    font-family: inherit;
    font-size: inherit;
    color: inherit;
  }
  .struct-item:hover {
    background: #fafaf8;
  }
  .struct-item.active {
    background: var(--accent-light);
    border-left: 3px solid var(--accent);
  }
  .struct-item .info {
    flex: 1;
    min-width: 0;
  }
  .struct-item .name {
    font-weight: 500;
    font-size: 0.95rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .type-badge {
    font-size: 0.7rem;
    padding: 1px 6px;
    border-radius: 8px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    white-space: nowrap;
  }
</style>
