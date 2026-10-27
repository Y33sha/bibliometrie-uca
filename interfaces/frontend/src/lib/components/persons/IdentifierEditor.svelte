<script lang="ts">
  import IdentifierLink from "#lib/components/IdentifierLink.svelte";
  import StatusToggles from "#lib/components/StatusToggles.svelte";
  import { autofocus } from "#lib/actions/focus.js";
  import { identifierTypeLabel } from "#lib/labels.js";
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
        : ident.status === "authenticated"
          ? "authentifié par le chercheur"
          : ident.status === "confirmed"
            ? "confirmé"
            : "en attente";
    return `${identifierTypeLabel(ident.id_type)} (${ident.source}) — ${label}`;
  }
</script>

{#if person.identifiers?.length}
  <div class="identifiers-row">
    {#each person.identifiers as ident}
      <div class="chip-row">
        {#if ident.status === "authenticated"}
          <span class="chip-controls">
            <span
              class="authenticated-badge"
              title="Authentifié par le chercheur — statut protégé, non modifiable"
              aria-label="Authentifié par le chercheur"
            >
              <svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">
                <path
                  d="M12 2 4 5v6c0 4.5 3.1 7.9 8 9 4.9-1.1 8-4.5 8-9V5l-8-3Z"
                  fill="currentColor"
                  opacity="0.15"
                />
                <path
                  d="M12 2 4 5v6c0 4.5 3.1 7.9 8 9 4.9-1.1 8-4.5 8-9V5l-8-3Z"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.6"
                />
                <path
                  d="m8.5 11.8 2.4 2.4 4.6-4.9"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </span>
          </span>
        {:else}
          <span class="chip-controls">
            <StatusToggles status={ident.status} onchange={(s) => onsetStatus(ident.id, s)} />
          </span>
        {/if}
        <span
          class="status-chip identifier-chip"
          class:confirmed={ident.status === "confirmed" || ident.status === "authenticated"}
          class:rejected={ident.status === "rejected"}
          title={identifierTitle(ident)}
        >
          {ident.id_value}
        </span>
        <IdentifierLink
          id_type={ident.id_type}
          id_value={ident.id_value}
          confirmed={ident.status === "confirmed" || ident.status === "authenticated"}
        />
      </div>
    {/each}
  </div>
{/if}
{#if form}
  <div class="id-form">
    <select class="select" aria-label="Type d'identifiant" bind:value={form.id_type}>
      {#each ["orcid", "idhal", "idref"] as idType (idType)}
        <option value={idType}>{identifierTypeLabel(idType)}</option>
      {/each}
    </select>
    <input
      type="text"
      placeholder={form.id_type === "orcid"
        ? "0000-0000-0000-0000"
        : form.id_type === "idhal"
          ? "identifiant-hal"
          : "identifiant idref"}
      bind:value={form.id_value}
      use:autofocus={{ select: true }}
      onkeydown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          onadd(person.id);
        } else if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          ontoggleForm(person.id);
        }
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
    font-family: var(--mono);
    font-size: 0.72rem;
  }
  /* Identifiant authentifié par le chercheur : statut protégé, aucune action — le bouclier remplace les boutons confirmer/rejeter. */
  .authenticated-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--success);
  }
  .btn-add-id {
    padding: 2px 8px;
    border: 1px dashed var(--border);
    border-radius: var(--radius);
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
  .id-form input {
    width: 180px;
    padding: 3px 6px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-size: 0.85rem;
    font-family: inherit;
  }
  .id-error {
    font-size: 0.8rem;
    color: var(--danger);
  }
</style>
