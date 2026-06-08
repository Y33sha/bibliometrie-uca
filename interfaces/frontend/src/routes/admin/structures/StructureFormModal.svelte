<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import { API_SOURCES, API_SOURCE_LABELS } from "./types";

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
    <label>Code (unique)</label>
    <input placeholder="ex: lpc, chu_clermont, site_cezeaux" bind:value={code} disabled={editMode} />
    <label>Nom complet</label>
    <input placeholder="ex: Laboratoire de Physique de Clermont" bind:value={name} />
    <label>Acronyme</label>
    <input placeholder="ex: LPC" bind:value={acronym} />
    <label>Type</label>
    <select bind:value={type}>
      <option value="labo">Laboratoire</option>
      <option value="universite">Université</option>
      <option value="onr">ONR</option>
      <option value="chu">CHU</option>
      <option value="ecole">École</option>
      <option value="site">Site</option>
      <option value="autre">Autre</option>
    </select>
    <label>ROR ID</label>
    <input placeholder="https://ror.org/0xxxxxxxxx" bind:value={ror} />
    <label>Collection HAL</label>
    <input placeholder="ex: INSTITUT_PASCAL" bind:value={hal} />
    <details class="api-ids-section">
      <summary>Identifiants API par source</summary>
      {#each API_SOURCES as src}
        <label class="api-id-label">{API_SOURCE_LABELS[src]}</label>
        <input placeholder="ex: id1, id2" bind:value={apiIds[src]} />
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
