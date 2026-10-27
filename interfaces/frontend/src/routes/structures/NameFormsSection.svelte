<script lang="ts">
  import HelpTip from "#lib/components/HelpTip.svelte";
  import IconButton from "#lib/components/IconButton.svelte";
  import Picker from "#lib/components/Picker.svelte";
  import type { NameForm, Structure } from "./types";
  import { SHORT_FORM_MAX_LENGTH } from "./types";

  let {
    structureId,
    forms,
    formsHelpOpen = $bindable(),
    addFormText = $bindable(),
    addFormWordBoundary = $bindable(),
    addFormExcluding = $bindable(),
    newFormCtx,
    ctxPickerOpen,
    ctxPickerFormId,
    ctxPickerResults,
    ctxPickerSearch = $bindable(),
    ctxPickerEl = $bindable(),
    ctxLabel,
    onaddForm,
    oneditForm,
    ondeleteForm,
    onremoveCtx,
    onremoveNewCtx,
    onopenCtxPicker,
    onpickCtx,
    onpickCtxShortcutTutelles,
    onpickCtxClear,
    oncloseCtxPicker,
  }: {
    structureId: number;
    forms: NameForm[];
    formsHelpOpen: boolean;
    addFormText: string;
    addFormWordBoundary: boolean;
    addFormExcluding: boolean;
    newFormCtx: (number | string)[];
    ctxPickerOpen: boolean;
    /** Forme dont on édite le contexte ; `null` pour la forme en cours d'ajout. */
    ctxPickerFormId: number | null;
    ctxPickerResults: Structure[];
    ctxPickerSearch: string;
    ctxPickerEl: HTMLDivElement | undefined;
    ctxLabel: (x: number | string) => string;
    onaddForm: (structId: number) => void | Promise<void>;
    oneditForm: (f: NameForm) => void;
    ondeleteForm: (formId: number) => void | Promise<void>;
    onremoveCtx: (formId: number, item: number | string) => void | Promise<void>;
    onremoveNewCtx: (item: number | string) => void;
    onopenCtxPicker: (formId: number | null) => void;
    onpickCtx: (item: number | string) => void | Promise<void>;
    onpickCtxShortcutTutelles: () => void;
    onpickCtxClear: () => void | Promise<void>;
    oncloseCtxPicker: () => void;
  } = $props();
</script>

<h3 class="section-title">Identification dans les publications</h3>

<h3>
  Formes de noms <span class="count-pill">{forms.length}</span>
  <button
    class="btn-help-icon"
    onclick={() => {
      formsHelpOpen = !formsHelpOpen;
    }}
    title="Aide"
    ><svg
      xmlns="http://www.w3.org/2000/svg"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      ><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line
        x1="12"
        y1="17"
        x2="12.01"
        y2="17"
      /></svg
    ></button
  >
</h3>
{#if formsHelpOpen}
  <p class="info-box">
    Les formes de nom servent à identifier les affiliations des publications via les adresses
    associées aux publications. Les changements seront pris en compte à la prochaine exécution du
    pipeline. Pour une prise en compte immédiate, relancer à partir de l'étape
    <code>affiliations</code> : <code>python run_pipeline.py --from affiliations</code>
  </p>
{/if}
<table class="data-table forms-table">
  <thead>
    <tr
      ><th class="col-badge"></th><th>Forme</th><th>Contexte requis <HelpTip text="La forme de nom identifie la structure seulement si au moins une autre structure est reconnue dans l'adresse." /></th><th></th></tr
    >
  </thead>
  <tbody>
    {#if forms.length === 0}
      <tr>
        <td colspan="4" style="text-align:center;color:var(--muted)"> Aucune forme </td>
      </tr>
    {:else}
      {#each forms as f (f.id)}
        <tr class:excluding={f.is_excluding}>
          <td class="col-badge">
            {#if f.is_excluding}<span class="match-badge excluding" title="Excluante"
                >excluante</span
              >
            {:else if f.is_word_boundary || f.form_text.length <= SHORT_FORM_MAX_LENGTH}<span
                class="match-badge word"
                title="Mot entier">mot entier</span
              >
            {:else}<span class="match-badge substr" title="Sous-chaîne">sous-chaîne</span>
            {/if}
          </td>
          <td class="form-text">{f.form_text}</td>
          <td>
            {#if f.is_excluding}
              <span class="none-label">—</span>
            {:else if f.requires_context_of?.length}
              {#each f.requires_context_of as x}
                <span class="ctx-tag">
                  {ctxLabel(x)}
                  <button class="ctx-remove" onclick={() => onremoveCtx(f.id, x)} title="Retirer ce contexte" aria-label="Retirer ce contexte">×</button>
                </span>
              {/each}
              {@render ctxAdd(f.id)}
            {:else}
              <span class="none-label">—</span>
              {@render ctxAdd(f.id)}
            {/if}
          </td>
          <td class="row-actions" style="white-space:nowrap">
            <IconButton icon="edit" label="Modifier la forme" onclick={() => oneditForm(f)} />
            <IconButton icon="delete" label="Supprimer la forme" onclick={() => ondeleteForm(f.id)} />
          </td>
        </tr>
      {/each}
    {/if}
  </tbody>
</table>

<!-- Add form row -->
<div class="add-row">
  <input
    placeholder="Nouvelle forme"
    bind:value={addFormText}
    onkeydown={(e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onaddForm(structureId);
      } else if (e.key === "Escape") {
        e.preventDefault();
        addFormText = "";
      }
    }}
  />
  <label class="checkbox-label">
    <input
      type="checkbox"
      checked={addFormWordBoundary || addFormText.length <= 6}
      disabled={addFormText.length <= 6}
      onchange={(e) => {
        addFormWordBoundary = (e.target as HTMLInputElement).checked;
      }}
    /> mot entier
  </label>
  <label class="checkbox-label">
    <input type="checkbox" bind:checked={addFormExcluding} /> excluante
  </label>
  <button class="btn btn-sm btn-primary" onclick={() => onaddForm(structureId)}> Ajouter </button>
</div>

<!-- New form context tags (masqué si excluante) -->
{#if !addFormExcluding}
  <div class="new-form-ctx">
    <span class="ctx-label-text">Contexte :</span>
    {#each newFormCtx as x}
      <span class="ctx-tag">
        {ctxLabel(x)}
        <button class="ctx-remove" onclick={() => onremoveNewCtx(x)} title="Retirer ce contexte" aria-label="Retirer ce contexte">×</button>
      </span>
    {/each}
    {@render ctxAdd(null)}
  </div>
{/if}

<!-- Ajout d'un contexte : le sélecteur s'ouvre à la place du bouton. -->
{#snippet ctxAdd(formId: number | null)}
  {#if ctxPickerOpen && ctxPickerFormId === formId}
    <Picker
      floating
      results={ctxPickerResults}
      bind:search={ctxPickerSearch}
      bind:element={ctxPickerEl}
      onpick={(cs) => onpickCtx(cs.id)}
      onclose={oncloseCtxPicker}
      placeholder="Rechercher une structure"
    >
      {#snippet header()}
        <div class="ctx-picker-shortcuts">
          <button class="btn btn-sm" onclick={onpickCtxShortcutTutelles}> tutelles </button>
          <button class="btn btn-sm" onclick={onpickCtxClear}> &#x2715; aucun contexte </button>
        </div>
      {/snippet}
      {#snippet item(cs)}
        <span class="structure-type structure-type-{cs.type}" style="font-size: 0.65rem;padding:0 5px">{cs.type}</span>
        {cs.acronym ? cs.acronym + " — " : ""}{cs.name}
      {/snippet}
    </Picker>
  {:else}
    <button class="btn-add" onclick={() => onopenCtxPicker(formId)}>+ contexte</button>
  {/if}
{/snippet}

<style>
  h3:not(.section-title) {
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 16px 0 8px;
    font-size: 0.95rem;
    font-weight: 600;
  }
  .count-pill {
    padding: 1px 8px;
    border-radius: var(--radius-pill);
    background: var(--surface);
    font-size: 0.75rem;
    color: var(--text-secondary);
  }
  .btn-help-icon {
    background: none;
    border: none;
    color: var(--muted);
    cursor: pointer;
    padding: 0;
    margin-left: 4px;
    vertical-align: middle;
    line-height: 1;
  }
  .btn-help-icon:hover {
    color: var(--accent);
  }
  .forms-table td {
    vertical-align: middle;
  }
  .forms-table td:last-child {
    width: 60px;
    text-align: right;
  }
  .forms-table .excluding {
    background: var(--attention-light);
  }
  .form-text {
    font-family: var(--mono);
    font-size: 0.85rem;
  }
  .col-badge {
    width: 1px;
    white-space: nowrap;
    padding-right: 0 !important;
  }
  .match-badge {
    font-size: 0.65rem;
    padding: 1px 5px;
    border-radius: var(--radius);
    font-weight: 500;
    white-space: nowrap;
  }
  .match-badge.word {
    background: var(--success-light);
    color: var(--success);
  }
  .match-badge.substr {
    background: var(--border-subtle);
    color: var(--muted);
  }
  .match-badge.excluding {
    background: var(--attention);
    color: white;
  }
  .ctx-tag {
    font-size: 0.7rem;
    padding: 1px 5px;
    border-radius: var(--radius);
    background: var(--warning-light);
    color: var(--warning-text);
    display: inline-flex;
    align-items: center;
    gap: 3px;
  }
  .ctx-remove {
    cursor: pointer;
    color: var(--danger);
    font-weight: bold;
    font-size: 0.85rem;
    line-height: 1;
    background: none;
    border: none;
    padding: 0;
    font-family: inherit;
  }
  .ctx-remove:hover {
    color: var(--danger);
  }
  .none-label {
    color: var(--muted);
  }
  /* Formulaire d'ajout sous le tableau, sur un fond léger. */
  .add-row {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 12px;
    padding: 10px 12px;
    align-items: center;
    background: var(--surface);
    border-radius: var(--radius);
  }
  .add-row input:not([type]) {
    flex: 1 1 260px;
    height: 34px;
    padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--card);
    font-size: 0.85rem;
    font-family: var(--mono);
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
  .new-form-ctx {
    margin-top: 4px;
    font-size: 0.85rem;
  }
  .ctx-label-text {
    color: var(--muted);
  }
  .ctx-picker-shortcuts {
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }
</style>
