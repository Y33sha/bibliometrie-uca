<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import type { EditFormState } from "./types";

  let {
    state = $bindable(),
    onsave,
    onclose,
  }: {
    state: EditFormState;
    onsave: () => void | Promise<void>;
    onclose: () => void;
  } = $props();
</script>

<Modal title="Modifier la forme de nom" maxWidth="460px" {onclose} onsubmit={onsave}>
    <label>Texte <input bind:value={state.form_text} /></label>
    <div class="modal-options">
      <label class="checkbox-label">
        <input
          type="checkbox"
          checked={state.is_word_boundary || state.form_text.length <= 6}
          disabled={state.form_text.length <= 6}
          onchange={(e) => {
            state.is_word_boundary = (e.target as HTMLInputElement).checked;
          }}
        /> Mot entier
      </label>
      <label class="checkbox-label">
        <input
          type="checkbox"
          checked={state.is_excluding}
          onchange={(e) => {
            state.is_excluding = (e.target as HTMLInputElement).checked;
          }}
        /> Excluante
      </label>
    </div>
    {#snippet actions()}
      <button class="btn" onclick={onclose}>Annuler</button>
      <button class="btn btn-primary" onclick={onsave}>Enregistrer</button>
    {/snippet}
</Modal>

<style>
  .modal-options {
    display: flex;
    gap: 16px;
    margin: 10px 0;
    font-size: 0.9rem;
  }
  .modal-options label {
    display: flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    font-weight: normal;
    margin: 0;
  }
  .checkbox-label {
    font-size: 0.8rem;
    display: flex;
    align-items: center;
    gap: 3px;
    margin: 0;
    cursor: pointer;
    white-space: nowrap;
  }
</style>
