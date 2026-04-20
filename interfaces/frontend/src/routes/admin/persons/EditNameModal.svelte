<script lang="ts">
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

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="modal-overlay" onclick={onclose}>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal-content modal-small" onclick={(e) => e.stopPropagation()}>
    <h3>Modifier le nom</h3>
    <div class="edit-name-form">
      <label>
        Nom
        <input
          type="text"
          bind:value={state.lastName}
          onkeydown={(e) => {
            if (e.key === "Enter") onsave();
          }}
        />
      </label>
      <label>
        Prénom
        <input
          type="text"
          bind:value={state.firstName}
          onkeydown={(e) => {
            if (e.key === "Enter") onsave();
          }}
        />
      </label>
    </div>
    <div class="modal-actions">
      {#if state.rejected}
        <button class="btn btn-restore" onclick={() => ontoggleReject(state.personId, false)}
          >Restaurer</button
        >
      {:else}
        <button class="btn btn-danger" onclick={() => ontoggleReject(state.personId, true)}
          >Rejeter (fausse entité)</button
        >
      {/if}
      <span style="flex:1"></span>
      <button class="btn" onclick={onclose}>Annuler</button>
      <button class="btn btn-confirm" onclick={onsave}>Enregistrer</button>
    </div>
  </div>
</div>

<style>
  .modal-small {
    max-width: 400px;
  }
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
  .btn-restore {
    background: #4caf50;
    color: white;
    border: none;
    padding: 6px 14px;
    border-radius: 4px;
    cursor: pointer;
  }
  .btn-restore:hover {
    background: #388e3c;
  }
</style>
