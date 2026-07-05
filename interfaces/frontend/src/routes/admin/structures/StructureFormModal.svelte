<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import { API_SOURCES, API_SOURCE_LABELS } from "./types";
  import { STRUCTURE_TYPES } from "$lib/structureTypes";

  let {
    editMode,
    code = $bindable(),
    name = $bindable(),
    acronym = $bindable(),
    type = $bindable(),
    ror = $bindable(),
    hal = $bindable(),
    apiIds = $bindable(),
    onclose,
    onsubmit,
  }: {
    editMode: boolean;
    code: string;
    name: string;
    acronym: string;
    type: string;
    ror: string;
    hal: string;
    apiIds: Record<string, string>;
    onclose: () => void;
    onsubmit: () => void | Promise<void>;
  } = $props();
</script>

<Modal
  title={editMode ? "Modifier la structure" : "Nouvelle structure"}
  maxWidth="460px"
  {onclose}
  {onsubmit}
>
    <label>Code (unique) <input placeholder="ex: lpc, chu_clermont, site_cezeaux" bind:value={code} disabled={editMode} /></label>
    <label>Nom complet <input placeholder="ex: Laboratoire de Physique de Clermont" bind:value={name} /></label>
    <label>Acronyme <input placeholder="ex: LPC" bind:value={acronym} /></label>
    <label>Type <select bind:value={type}>
      {#each STRUCTURE_TYPES as t (t.value)}
        <option value={t.value}>{t.label}</option>
      {/each}
    </select></label>
    <label>ROR ID <input placeholder="0xxxxxxxxx" bind:value={ror} /></label>
    <label>Collection HAL <input placeholder="ex: INSTITUT_PASCAL" bind:value={hal} /></label>
    <details class="api-ids-section">
      <summary>Identifiants API par source</summary>
      {#each API_SOURCES as src}
        <label class="api-id-label">{API_SOURCE_LABELS[src]} <input placeholder="ex: id1, id2" bind:value={apiIds[src]} /></label>
      {/each}
    </details>
    {#snippet actions()}
      <button class="btn" onclick={onclose}>Annuler</button>
      <button class="btn btn-primary" onclick={onsubmit}>
        {editMode ? "Enregistrer" : "Créer"}
      </button>
    {/snippet}
</Modal>

<style>
  .api-ids-section {
    margin-top: 10px;
    padding: 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface-hover);
  }
  .api-ids-section summary {
    cursor: pointer;
    font-size: 0.85rem;
    color: var(--muted);
    font-weight: 500;
  }
  .api-id-label {
    font-size: 0.8rem;
    color: var(--muted);
    margin-top: 6px;
  }
</style>
