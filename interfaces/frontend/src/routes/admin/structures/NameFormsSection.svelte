<script lang="ts">
  import Picker from "$lib/components/Picker.svelte";
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
  Formes de noms ({forms.length})
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
  <p class="help-text">
    Les formes de nom servent à identifier les affiliations des publications via les adresses
    associées aux publications. Les changements seront pris en compte à la prochaine exécution du
    pipeline. Pour une prise en compte immédiate, relancer à partir de l'étape
    <code>affiliations</code> : <code>python run_pipeline.py --from affiliations</code>
  </p>
{/if}
<table class="forms-table">
  <thead>
    <tr
      ><th class="col-badge"></th><th>Forme</th><th>Contexte requis</th><th></th></tr
    >
  </thead>
  <tbody>
    {#if forms.length === 0}
      <tr>
        <td colspan="4" style="text-align:center;color:var(--text-muted)"> Aucune forme </td>
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
              <span class="sufficient-label">—</span>
            {:else if f.requires_context_of?.length}
              {#each f.requires_context_of as x}
                <span class="ctx-tag">
                  {ctxLabel(x)}
                  <button class="ctx-remove" onclick={() => onremoveCtx(f.id, x)}>x</button>
                </span>
              {/each}
              <button class="btn-add-tiny" onclick={() => onopenCtxPicker(f.id)}> + </button>
            {:else}
              <span class="sufficient-label">suffisant</span>
              <button class="btn-add-tiny" onclick={() => onopenCtxPicker(f.id)}> + </button>
            {/if}
          </td>
          <td style="white-space:nowrap">
            <button class="btn-icon" onclick={() => oneditForm(f)} title="Modifier">
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                ><path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z" /><path
                  d="m15 5 4 4"
                /></svg
              >
            </button>
            <button
              class="btn-icon btn-icon-danger"
              onclick={() => ondeleteForm(f.id)}
              title="Supprimer"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
                ><line x1="18" y1="6" x2="6" y2="18" /><line
                  x1="6"
                  y1="6"
                  x2="18"
                  y2="18"
                /></svg
              >
            </button>
          </td>
        </tr>
      {/each}
    {/if}
  </tbody>
</table>

<!-- Add form row -->
<div class="add-row">
  <input
    placeholder="Nouvelle forme..."
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
        <button class="ctx-remove" onclick={() => onremoveNewCtx(x)}>x</button>
      </span>
    {/each}
    <button class="btn-add-tiny" onclick={() => onopenCtxPicker(null)}>+</button>
    {#if newFormCtx.length === 0}
      <span class="ctx-hint">(suffisant)</span>
    {/if}
  </div>
{/if}

<!-- Context picker -->
{#if ctxPickerOpen}
  <Picker
    results={ctxPickerResults}
    bind:search={ctxPickerSearch}
    bind:element={ctxPickerEl}
    onpick={(cs) => onpickCtx(cs.id)}
    onclose={oncloseCtxPicker}
    placeholder="Rechercher une structure…"
  >
    {#snippet header()}
      <div class="ctx-picker-shortcuts">
        <button class="btn btn-sm" onclick={onpickCtxShortcutTutelles}> tutelles </button>
        <button class="btn btn-sm" onclick={onpickCtxClear}> &#x2715; suffisant </button>
      </div>
    {/snippet}
    {#snippet item(cs)}
      <span class="type-badge type-{cs.type}" style="font-size: 0.65rem;padding:0 5px">{cs.type}</span>
      {cs.acronym ? cs.acronym + " — " : ""}{cs.name}
    {/snippet}
  </Picker>
{/if}

<style>
  .section-title {
    margin: 20px -14px 10px !important;
    padding: 6px 14px !important;
    background: #5b9ea0;
    color: white !important;
    font-size: 0.75rem !important;
    border-radius: 3px;
  }
  h3 {
    margin: 12px 0 6px;
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text-muted);
    text-transform: uppercase;
    letter-spacing: 0.5px;
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
  .help-text {
    background: var(--accent-light);
    border: 1px solid #c4d8ed;
    border-radius: 5px;
    padding: 8px 12px;
    margin: 4px 0 8px;
    font-size: 0.85rem;
    color: #2c3e50;
    line-height: 1.5;
  }
  .forms-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.95rem;
  }
  .forms-table th {
    text-align: left;
    padding: 5px 8px;
    font-size: 0.8rem;
    color: var(--text-muted);
    border-bottom: 2px solid var(--border);
    font-weight: 600;
  }
  .forms-table td {
    padding: 5px 8px;
    border-bottom: 1px solid var(--border-subtle);
    vertical-align: middle;
  }
  .forms-table td:last-child {
    width: 60px;
    text-align: right;
  }
  .forms-table .excluding {
    background: #fff3e0;
  }
  .form-text {
    font-family: "SF Mono", Consolas, monospace;
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
    border-radius: 8px;
    font-weight: 500;
    white-space: nowrap;
  }
  .match-badge.word {
    background: #e8f0e8;
    color: #2e6b2e;
  }
  .match-badge.substr {
    background: #f0f0f0;
    color: #888;
  }
  .match-badge.excluding {
    background: #e65100;
    color: white;
  }
  .ctx-tag {
    font-size: 0.7rem;
    padding: 1px 5px;
    border-radius: 6px;
    background: var(--warning-light);
    color: #8a6d10;
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
  .sufficient-label {
    color: var(--success);
    font-size: 0.8rem;
  }
  .btn-icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 26px;
    height: 26px;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: none;
    cursor: pointer;
    color: var(--muted);
  }
  .btn-icon:hover {
    background: var(--hover);
    color: var(--accent);
    border-color: var(--accent);
  }
  .btn-icon-danger:hover {
    color: var(--danger);
    border-color: var(--danger);
  }
  .btn-add-tiny {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 1px solid var(--border);
    background: white;
    color: var(--accent);
    font-size: 0.8rem;
    font-weight: bold;
    cursor: pointer;
    vertical-align: middle;
    line-height: 1;
    padding: 0;
  }
  .btn-add-tiny:hover {
    background: var(--accent);
    color: white;
    border-color: var(--accent);
  }
  .add-row {
    display: flex;
    gap: 4px;
    margin-top: 8px;
    align-items: center;
  }
  .add-row input:not([type]) {
    flex: 1;
    padding: 4px 6px;
    border: 1px solid var(--border);
    border-radius: 3px;
    font-size: 0.85rem;
    font-family: inherit;
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
    color: var(--text-muted);
  }
  .ctx-hint {
    color: var(--text-muted);
    font-size: 0.8rem;
    margin-left: 4px;
  }
  .ctx-picker-shortcuts {
    padding: 6px 10px;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 4px;
    flex-wrap: wrap;
  }
</style>
