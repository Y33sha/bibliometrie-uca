<script lang="ts">
  import { base } from "$app/paths";
  import Modal from "$lib/components/Modal.svelte";
  import { sanitizeTitle } from "$lib/utils";
  import { sourceLabel } from "$lib/sources";
  import type { DetachModalState } from "./types";

  let {
    state = $bindable(),
    onclose,
    onconfirmDetach,
    onmerge,
  }: {
    state: DetachModalState;
    onclose: () => void;
    onconfirmDetach: () => void | Promise<void>;
    onmerge: (sourceId: number) => void | Promise<void>;
  } = $props();

  const checkedCount = $derived(state.publications.filter((p) => p.checked).length);
  const allChecked = $derived(
    state.publications.length > 0 && state.publications.every((p) => p.checked),
  );

  function setAll(checked: boolean): void {
    for (const p of state.publications) p.checked = checked;
  }
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
        {#if state.publications.length > 1}
          <label class="checkbox-row detach-all">
            <input
              type="checkbox"
              checked={allChecked}
              onchange={(e) => setAll(e.currentTarget.checked)}
            />
            {allChecked ? "Tout décocher" : "Tout cocher"}
          </label>
        {/if}
        <div class="detach-list">
          {#each state.publications as p, i}
            <div class="detach-item">
              <input type="checkbox" bind:checked={state.publications[i].checked} />
              <span class="detach-year">{p.pub_year ?? "?"}</span>
              <a
                class="detach-title"
                href="{base}/publications/{p.pub_id}"
                target="_blank"
                rel="noopener"
              >{@html sanitizeTitle(p.title)}</a>
              <span class="detach-sources">
                {#each p.sources as s}
                  <span class="tag tag-source">{sourceLabel(s.source)}</span>
                {/each}
              </span>
            </div>
          {/each}
        </div>
      {/if}
    {/if}
  {#snippet actions()}
    {#if !state.loading}
      <button class="btn" onclick={onclose}>Annuler</button>
      <button class="btn btn-danger" disabled={checkedCount === 0} onclick={onconfirmDetach}>
        Détacher {checkedCount} publication{checkedCount > 1 ? "s" : ""}
      </button>
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
  .detach-all {
    margin: 12px 0 4px;
    /* Aligne la case sur celles des rangées (padding-left de .detach-item). */
    padding-left: 8px;
  }
  .detach-item {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 4px 8px;
    border-radius: 4px;
  }
  .detach-item:hover {
    background: #f5f5f5;
  }
  .detach-item input[type="checkbox"] {
    /* Annule le `.modal-content input { width: 100% }` global qui étirait la case
       sur toute la largeur et écrasait le titre. Marges à 0 (sauf le top) pour aligner
       sur la case « tout cocher » (`.checkbox-row input { margin: 0 }`). */
    width: auto;
    flex-shrink: 0;
    margin: 2px 0 0;
  }
  .detach-year {
    color: #888;
    font-size: 0.8rem;
    min-width: 30px;
    flex-shrink: 0;
  }
  .detach-title {
    flex: 1;
    min-width: 0;
    font-size: 0.85rem;
    color: var(--text);
    text-decoration: none;
  }
  .detach-title:hover {
    color: var(--accent);
    text-decoration: underline;
  }
  .detach-sources {
    flex-shrink: 0;
    max-width: 120px;
    text-align: right;
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
