<script lang="ts">
  import { tooltip } from "#lib/actions/tooltip.svelte.js";
  import ShieldCheck from "@lucide/svelte/icons/shield-check";
  import IdentifierLink from "#lib/components/IdentifierLink.svelte";
  import StatusToggles from "#lib/components/StatusToggles.svelte";
  import RejectedFold from "./RejectedFold.svelte";
  import { autofocus } from "#lib/actions/focus.js";
  import { identifierTypeLabel, PERSON_IDENTIFIER_TYPES } from "#lib/labels.js";
  import type { IdFormState, Person, PersonIdentifier } from "./types";
  import IconButton from "#lib/components/IconButton.svelte";

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

  const activeIdentifiers = $derived((person.identifiers ?? []).filter((i) => i.status !== "rejected"));
  const rejectedIdentifiers = $derived((person.identifiers ?? []).filter((i) => i.status === "rejected"));
</script>

{#snippet identifierRow(ident: PersonIdentifier)}
  <div class="chip-row">
    {#if ident.status === "authenticated"}
      <span class="chip-controls">
        <span
          class="authenticated-badge"
          use:tooltip={'Authentifié par le chercheur — statut protégé, non modifiable'}
          aria-label="Authentifié par le chercheur"
        >
          <ShieldCheck size={15} />
        </span>
      </span>
    {:else}
      <span class="chip-controls">
        <StatusToggles status={ident.status} onchange={(s) => onsetStatus(ident.id, s)} />
      </span>
    {/if}
    <span
      class="tag status-chip identifier-chip"
      class:confirmed={ident.status === "confirmed" || ident.status === "authenticated"}
      class:rejected={ident.status === "rejected"}
      use:tooltip={identifierTitle(ident)}
    >
      {ident.id_value}
    </span>
    <IdentifierLink
      id_type={ident.id_type}
      id_value={ident.id_value}
      confirmed={ident.status === "confirmed" || ident.status === "authenticated"}
    />
  </div>
{/snippet}

{#if activeIdentifiers.length}
  <div class="identifiers-row">
    {#each activeIdentifiers as ident}
      {@render identifierRow(ident)}
    {/each}
  </div>
{/if}
{#if form}
  <div class="id-form">
    <select class="select" aria-label="Type d'identifiant" bind:value={form.id_type}>
      {#each PERSON_IDENTIFIER_TYPES as idType (idType)}
        <option value={idType}>{identifierTypeLabel(idType)}</option>
      {/each}
    </select>
    <input
      type="text"
      class="input-sm"
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
    <button class="btn btn-create" onclick={() => onadd(person.id)}>OK</button>
    <IconButton icon="reject" label="Annuler" onclick={() => ontoggleForm(person.id)} />
    {#if form.error}
      <span class="id-error">{form.error}</span>
    {/if}
  </div>
{:else}
  <button
    class="btn-add btn-add-id"
    use:tooltip={'Ajouter un identifiant'}
    onclick={() => ontoggleForm(person.id)}>+ Identifiant</button
  >
{/if}
{#if rejectedIdentifiers.length}
  <RejectedFold personId={person.id} label="les identifiants rejetés">
    <div class="identifiers-row">
      {#each rejectedIdentifiers as ident}
        {@render identifierRow(ident)}
      {/each}
    </div>
  </RejectedFold>
{/if}

<style>
  .identifiers-row {
    display: flex;
    flex-direction: column;
    gap: 4px;
    align-items: flex-start;
    margin-bottom: 6px;
  }
  .identifier-chip {
    font-family: var(--mono);
  }
  /* Identifiant authentifié par le chercheur : statut protégé, aucune action — le bouclier remplace les boutons confirmer/rejeter. */
  .authenticated-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--success);
  }
  .btn-add-id {
    margin-top: 4px;
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
  }
  .id-error {
    font-size: var(--fs-sm);
    color: var(--danger);
  }
</style>
