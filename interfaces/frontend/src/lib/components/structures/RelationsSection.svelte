<script lang="ts">
  import Picker from "#lib/components/Picker.svelte";
  import { structureLabel } from "#lib/structureLabels.js";
  import StructureTypeTag from "./StructureTypeTag.svelte";
  import type { RelatedStructure, Structure } from "./types";
  import IconButton from "#lib/components/IconButton.svelte";

  let {
    structureId,
    tutelles,
    tutellesDe,
    relationPickerOpen,
    pickerDirection,
    relationPickerResults,
    relationPickerSearch = $bindable(),
    relationPickerEl = $bindable(),
    onselect,
    ondeleteTutelle,
    onopenPicker,
    onpickStructure,
    onclosePicker,
  }: {
    structureId: number;
    tutelles: RelatedStructure[];
    tutellesDe: RelatedStructure[];
    relationPickerOpen: boolean;
    /** Ligne où le sélecteur est ouvert : `parent` (tutelles) ou `child` (est tutelle de). */
    pickerDirection: string;
    relationPickerResults: Structure[];
    relationPickerSearch: string;
    relationPickerEl: HTMLDivElement | undefined;
    onselect: (id: number) => void | Promise<void>;
    ondeleteTutelle: (tutelleId: number) => void | Promise<void>;
    onopenPicker: (direction: string, structId: number) => void;
    onpickStructure: (otherId: number) => void | Promise<void>;
    onclosePicker: () => void;
  } = $props();
</script>

<h3 class="section-title">Tutelles</h3>

<div class="relations">
  {@render relationRow("Tutelles", tutelles, "Aucune", "parent")}
  {@render relationRow("Est tutelle de", tutellesDe, "Aucune structure", "child")}
</div>

{#snippet relationRow(label: string, related: RelatedStructure[], emptyText: string, direction: string)}
  <span class="relation-label">{label}</span>
  <div class="relation-values">
    {#if related.length === 0}
      <span class="none-text">{emptyText}</span>
    {:else}
      {#each related as r (r.tutelle_id)}
        <span class="tag-removable">
          <span class="tag tag-pill tag-accent relation-tag">
            <button class="tag-name" onclick={() => onselect(r.id)}>{structureLabel(r)}</button>
          </span>
          <IconButton icon="reject" label="Retirer {structureLabel(r)}" onclick={() => ondeleteTutelle(r.tutelle_id)} />
        </span>
      {/each}
    {/if}
    {#if relationPickerOpen && pickerDirection === direction}
      <Picker
        floating
        results={relationPickerResults}
        bind:search={relationPickerSearch}
        bind:element={relationPickerEl}
        onpick={(rs) => onpickStructure(rs.id)}
        onclose={onclosePicker}
        placeholder="Rechercher une structure"
      >
        {#snippet item(rs)}
          <StructureTypeTag type={rs.type} />
          {rs.acronym ? rs.acronym + " — " : ""}{rs.name}
        {/snippet}
      </Picker>
    {:else}
      <button class="btn-add" onclick={() => onopenPicker(direction, structureId)}>+ Ajouter</button>
    {/if}
  </div>
{/snippet}


<style>
  .relations {
    display: grid;
    grid-template-columns: 180px 1fr;
    gap: 12px 20px;
    align-items: baseline;
    font-size: var(--fs-md);
  }
  .relation-label {
    color: var(--text-secondary);
  }
  .relation-values {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .relation-tag .tag-name {
    padding: 0;
    border: none;
    background: none;
    font: inherit;
    color: inherit;
    cursor: pointer;
  }
  .relation-tag .tag-name:hover {
    text-decoration: underline;
  }
  .none-text {
    color: var(--muted);
  }
</style>
