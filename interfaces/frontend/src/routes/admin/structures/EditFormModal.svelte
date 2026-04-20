<script lang="ts">
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

<!-- svelte-ignore a11y_click_events_have_key_events -->
<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="modal-bg" onclick={onclose}>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div class="modal" onclick={(e) => e.stopPropagation()}>
    <h3>Modifier la forme de nom</h3>
    <label>Texte</label>
    <input bind:value={state.form_text} />
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
    <div class="actions">
      <button class="btn" onclick={onclose}>Annuler</button>
      <button class="btn btn-primary" onclick={onsave}>Enregistrer</button>
    </div>
  </div>
</div>

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
