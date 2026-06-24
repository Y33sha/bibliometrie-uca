<script lang="ts">
  import Picker from "$lib/components/Picker.svelte";
  import type { RelatedStructure, Structure } from "./types";

  let {
    structureId,
    tutelles,
    tutellesDe,
    partenaires,
    relationPickerOpen,
    relationPickerResults,
    relationPickerSearch = $bindable(),
    relationPickerEl = $bindable(),
    onselect,
    ondeleteRelation,
    onopenPicker,
    onpickStructure,
    onclosePicker,
  }: {
    structureId: number;
    tutelles: RelatedStructure[];
    tutellesDe: RelatedStructure[];
    partenaires: (RelatedStructure & { id_struct: number })[];
    relationPickerOpen: boolean;
    relationPickerResults: Structure[];
    relationPickerSearch: string;
    relationPickerEl: HTMLDivElement | undefined;
    onselect: (id: number) => void | Promise<void>;
    ondeleteRelation: (relId: number) => void | Promise<void>;
    onopenPicker: (relType: string, direction: string, structId: number) => void;
    onpickStructure: (otherId: number) => void | Promise<void>;
    onclosePicker: () => void;
  } = $props();
</script>

<h3 class="section-title">Relations</h3>

<!-- Tutelles -->
<h3>
  Tutelle{tutelles.length > 1 ? "s" : ""}
  <button class="btn-add" onclick={() => onopenPicker("est_tutelle_de", "parent", structureId)}
    >+</button
  >
</h3>
<div>
  {#if tutelles.length === 0}
    <span class="none-text">Aucune</span>
  {:else}
    {#each tutelles as p (p.relation_id)}
      <span class="tag tutelle">
        <button class="tag-name" onclick={() => onselect(p.id)}>
          {p.acronym || p.name}
        </button>
        <button class="remove" onclick={() => ondeleteRelation(p.relation_id)} title="Supprimer"
          >x</button
        >
      </span>
    {/each}
  {/if}
</div>

<!-- Est tutelle de -->
<h3>
  Est tutelle de
  <button class="btn-add" onclick={() => onopenPicker("est_tutelle_de", "child", structureId)}
    >+</button
  >
</h3>
<div>
  {#if tutellesDe.length === 0}
    <span class="none-text">Aucun</span>
  {:else}
    {#each tutellesDe as c (c.relation_id)}
      <span class="tag tutelle">
        <button class="tag-name" onclick={() => onselect(c.id)}>
          {c.acronym || c.name}
        </button>
        <button class="remove" onclick={() => ondeleteRelation(c.relation_id)} title="Supprimer"
          >x</button
        >
      </span>
    {/each}
  {/if}
</div>

<!-- Partenaires -->
<h3>
  Partenaire{partenaires.length > 1 ? "s" : ""}
  <button class="btn-add" onclick={() => onopenPicker("est_partenaire_de", "parent", structureId)}
    >+</button
  >
</h3>
<div>
  {#if partenaires.length === 0}
    <span class="none-text">Aucun</span>
  {:else}
    {#each partenaires as p (p.relation_id)}
      <span class="tag partenaire">
        <button class="tag-name" onclick={() => onselect(p.id_struct)}>
          {p.acronym || p.name}
        </button>
        <button class="remove" onclick={() => ondeleteRelation(p.relation_id)} title="Supprimer"
          >x</button
        >
      </span>
    {/each}
  {/if}
</div>

<!-- Relation picker -->
{#if relationPickerOpen}
  <Picker
    results={relationPickerResults}
    bind:search={relationPickerSearch}
    bind:element={relationPickerEl}
    onpick={(rs) => onpickStructure(rs.id)}
    onclose={onclosePicker}
    placeholder="Rechercher une structure…"
  >
    {#snippet item(rs)}
      <span class="type-badge type-{rs.type}" style="font-size: 0.65rem;padding:0 5px">{rs.type}</span>
      {rs.acronym ? rs.acronym + " — " : ""}{rs.name}
    {/snippet}
  </Picker>
{/if}

<style>
  .section-title {
    margin: 20px -14px 10px !important;
    padding: 6px 14px !important;
    background: #5b9ea0;
    color: white !important;
    font-size: 0.75rem !important;
    border-radius: 3px;
  }
  .tag {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.85rem;
    padding: 2px 8px;
    border-radius: 10px;
    margin: 2px;
    background: #f0f0f0;
  }
  .tag .tag-name {
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    color: inherit;
  }
  .tag .tag-name:hover {
    text-decoration: underline;
  }
  .tag .remove {
    cursor: pointer;
    color: var(--danger);
    font-weight: bold;
    font-size: 1rem;
    line-height: 1;
    background: none;
    border: none;
    padding: 0;
    font-family: inherit;
  }
  .tag .remove:hover {
    color: var(--danger);
  }
  .tag.tutelle {
    background: #d4e8f0;
    color: #2e6b8a;
  }
  .tag.partenaire {
    background: #f0e8d4;
    color: #8a6b2e;
  }
  .none-text {
    font-size: 0.85rem;
    color: var(--text-muted);
  }
  .btn-add {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: white;
    color: var(--accent);
    font-size: 0.85rem;
    font-weight: bold;
    cursor: pointer;
    margin-left: 6px;
    vertical-align: middle;
    line-height: 1;
    padding: 0 0 1px 0;
  }
  .btn-add:hover {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }
  h3 {
    margin: 12px 0 6px;
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
  }
</style>
