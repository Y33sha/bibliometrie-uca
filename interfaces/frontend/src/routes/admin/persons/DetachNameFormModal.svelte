<script lang="ts">
  import Modal from "$lib/components/Modal.svelte";
  import { sanitizeTitle } from "$lib/utils";
  import { sourceLabels } from "$lib/labels";
  import type { DetachModalState } from "./types";

  let {
    state = $bindable(),
    onclose,
    onconfirmDetach,
    ondetachNameForm,
    onmerge,
  }: {
    state: DetachModalState;
    onclose: () => void;
    onconfirmDetach: () => void | Promise<void>;
    ondetachNameForm: () => void | Promise<void>;
    onmerge: (sourceId: number) => void | Promise<void>;
  } = $props();
</script>

<Modal title={`Forme de nom : « ${state.nameForm} »`} {onclose}>
    {#if state.loading}
      <p>Chargement…</p>
    {:else}
      {#if state.otherPersons.length > 0}
        <div class="other-persons-section">
          <h4>Autres personnes partageant cette forme de nom</h4>
          <div class="other-persons-list">
            {#each state.otherPersons as op}
              <div class="other-person-row">
                <span class="other-person-name">
                  {op.first_name} <strong>{op.last_name}</strong>
                  {#if op.department_name}<span class="other-person-dept"
                      >({op.department_name})</span
                    >{/if}
                  {#if op.has_rh}<span class="tag tag-rh">RH</span>{/if}
                </span>
                <button class="btn btn-sm btn-merge-modal" onclick={() => onmerge(op.id)}>
                  ← Fusionner
                </button>
              </div>
            {/each}
          </div>
        </div>
      {/if}
      {#if state.publications.length === 0}
        <p>Aucune publication liée.</p>
      {:else}
        <p>Cochez les publications à détacher de cette personne :</p>
        <div class="detach-list">
          {#each state.publications as p, i}
            <label class="detach-item">
              <input type="checkbox" bind:checked={state.publications[i].checked} />
              <span class="detach-year">{p.pub_year ?? "?"}</span>
              <span class="detach-title">{@html sanitizeTitle(p.title)}</span>
              <span class="detach-sources">
                {#each p.sources as s}
                  <span class="tag tag-source">{sourceLabels[s.source] ?? s.source}</span>
                {/each}
              </span>
            </label>
          {/each}
        </div>
      {/if}
    {/if}
  {#snippet actions()}
    {#if !state.loading}
      <button class="btn" onclick={onclose}>Annuler</button>
      {#if state.publications.length === 0}
        <button class="btn btn-danger" onclick={ondetachNameForm}>Détacher cette forme</button>
      {:else}
        <button class="btn btn-danger" onclick={onconfirmDetach}>
          Détacher {state.publications.filter((p) => p.checked).length} publication{state.publications.filter(
            (p) => p.checked,
          ).length > 1
            ? "s"
            : ""}
        </button>
      {/if}
    {/if}
  {/snippet}
</Modal>

<style>
  .detach-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin: 12px 0;
  }
  .detach-item {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 8px;
    border-radius: 4px;
    cursor: pointer;
  }
  .detach-item:hover {
    background: #f5f5f5;
  }
  .detach-year {
    color: #888;
    font-size: 0.8rem;
    min-width: 30px;
  }
  .detach-title {
    font-size: 0.85rem;
  }
  .other-persons-section {
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid #e0e0e0;
  }
  .other-persons-section h4 {
    margin: 0 0 8px;
    font-size: 0.9rem;
    color: #666;
  }
  .other-persons-list {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .other-person-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .other-person-row:hover {
    background: #f5f5f5;
  }
  .other-person-name {
    font-size: 0.9rem;
  }
  .other-person-dept {
    color: #888;
    font-size: 0.8rem;
  }
  .btn-merge-modal {
    background: #1976d2;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }
  .btn-merge-modal:hover {
    background: #1565c0;
  }
  .tag {
    display: inline-block;
    font-size: 0.8rem;
    padding: 1px 7px;
    border-radius: 10px;
    font-weight: 500;
    margin: 1px 2px;
  }
  .tag-source {
    background: #eee;
    color: #555;
    font-size: 0.7rem;
  }
</style>
