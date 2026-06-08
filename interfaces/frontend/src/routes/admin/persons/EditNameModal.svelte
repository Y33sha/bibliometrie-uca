<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import type { EditNameState } from "./types";

  let {
    state = $bindable(),
    onsave,
    ontoggleReject,
    onclose,
  }: {
    state: EditNameState;
    onsave: () => void | Promise<void>;
    ontoggleReject: (personId: number, rejected: boolean) => void | Promise<void>;
    onclose: () => void;
  } = $props();
</script>

<Modal title="Modifier le nom" maxWidth="400px" {onclose} onsubmit={onsave}>
    <div class="edit-name-form">
      <label>
        Nom
        <input type="text" bind:value={state.lastName} />
      </label>
      <label>
        Prénom
        <input type="text" bind:value={state.firstName} />
      </label>
    </div>
    {#snippet actions()}
      {#if state.rejected}
        <button class="btn btn-confirm" onclick={() => ontoggleReject(state.personId, false)}
          >Restaurer</button
        >
      {:else}
        <button class="btn btn-danger" onclick={() => ontoggleReject(state.personId, true)}
          >Rejeter (fausse entité)</button
        >
      {/if}
      <span style="flex:1"></span>
      <button class="btn" onclick={onclose}>Annuler</button>
      <button class="btn btn-primary" onclick={onsave}>Enregistrer</button>
    {/snippet}
</Modal>

<style>
  .edit-name-form {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin: 12px 0;
  }
  .edit-name-form label {
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 0.85rem;
    font-weight: 500;
  }
  .edit-name-form input {
    padding: 6px 8px;
    border: 1px solid #ccc;
    border-radius: 4px;
    font-size: 0.9rem;
  }
</style>
