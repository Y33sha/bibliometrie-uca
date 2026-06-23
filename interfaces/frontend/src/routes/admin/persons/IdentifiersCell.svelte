<script lang="ts">
  import type { IdFormState, Person, PersonIdentifier } from "./types";

  let {
    person,
    form,
    onadd,
    ontoggleForm,
    onsetStatus,
  }: {
    person: Person;
    /** État du formulaire d'ajout pour cette personne (null = pas ouvert). */
    form: IdFormState | null;
    onadd: (personId: number) => void | Promise<void>;
    ontoggleForm: (personId: number) => void;
    onsetStatus: (identId: number, status: string) => void | Promise<void>;
  } = $props();

  function identifierTitle(ident: PersonIdentifier): string {
    const label =
      ident.status === "rejected"
        ? "rejeté"
        : ident.status === "confirmed"
          ? "confirmé"
          : "en attente";
    return `${ident.id_type} (${ident.source}) — ${label}`;
  }

  function identifierLabel(ident: PersonIdentifier): string {
    const type =
      ident.id_type === "orcid"
        ? "ORCID"
        : ident.id_type === "idhal"
          ? "idHAL"
          : ident.id_type;
    return `${type}: ${ident.id_value}`;
  }
</script>

{#if person.identifiers?.length}
  <div class="identifiers-row">
    {#each person.identifiers as ident}
      <div class="chip-row">
        <span
          class="status-chip identifier-chip"
          class:confirmed={ident.status === "confirmed"}
          class:rejected={ident.status === "rejected"}
          title={identifierTitle(ident)}
        >
          {identifierLabel(ident)}
        </span>
        <button
          class="status-btn confirm"
          class:active={ident.status === "confirmed"}
          title={ident.status === "confirmed" ? "Retirer la confirmation" : "Confirmer"}
          onclick={() =>
            onsetStatus(ident.id, ident.status === "confirmed" ? "pending" : "confirmed")}
          >&#x2713;</button
        >
        <button
          class="status-btn reject"
          class:active={ident.status === "rejected"}
          title={ident.status === "rejected" ? "Retirer le rejet" : "Rejeter"}
          onclick={() =>
            onsetStatus(ident.id, ident.status === "rejected" ? "pending" : "rejected")}
          >&#x2717;</button
        >
      </div>
    {/each}
  </div>
{/if}
{#if form}
  <div class="id-form">
    <select bind:value={form.id_type}>
      <option value="orcid">ORCID</option>
      <option value="idhal">idHAL</option>
      <option value="idref">IdRef</option>
    </select>
    <input
      type="text"
      placeholder={form.id_type === "orcid"
        ? "0000-0000-0000-0000"
        : form.id_type === "idhal"
          ? "identifiant-hal"
          : "identifiant idref"}
      bind:value={form.id_value}
      onkeydown={(e) => {
        if (e.key === "Enter") onadd(person.id);
      }}
    />
    <button class="btn btn-link" onclick={() => onadd(person.id)}>OK</button>
    <button class="btn" onclick={() => ontoggleForm(person.id)}>&times;</button>
    {#if form.error}
      <span class="id-error">{form.error}</span>
    {/if}
  </div>
{:else}
  <button
    class="btn btn-add-id"
    title="Ajouter un identifiant"
    onclick={() => ontoggleForm(person.id)}>+ Identifiant</button
  >
{/if}

<style>
  .identifiers-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: flex-start;
    margin-bottom: 6px;
  }
  .chip-row {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .identifier-chip {
    font-family: "SF Mono", SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
    font-size: 0.72rem;
  }
  .btn-add-id {
    padding: 2px 8px;
    border: 1px dashed var(--border);
    border-radius: 4px;
    background: none;
    font-size: 0.8rem;
    cursor: pointer;
    color: var(--accent);
    margin-top: 4px;
    font-family: inherit;
  }
  .btn-add-id:hover {
    background: var(--accent-light);
    border-style: solid;
  }
  .btn-link {
    border-color: var(--success);
    color: var(--success);
  }
  .btn-link:hover {
    background: var(--success);
    color: white;
  }
  .id-form {
    display: flex;
    align-items: center;
    gap: 4px;
    margin-top: 4px;
    flex-wrap: wrap;
  }
  .id-form select,
  .id-form input {
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: 3px;
    font-size: 0.85rem;
    font-family: inherit;
  }
  .id-form select {
    width: 80px;
  }
  .id-form input {
    width: 180px;
  }
  .id-error {
    font-size: 0.8rem;
    color: var(--danger);
  }
</style>
