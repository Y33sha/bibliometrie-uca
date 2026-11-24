<script lang="ts">
  import { tooltip } from "#lib/actions/tooltip.svelte.js";
  import IconButton from "#lib/components/IconButton.svelte";
  import RhCheck from "#lib/components/RhCheck.svelte";
  import { resolve } from "$app/paths";
  import { api } from "#lib/api/index.js";
  import { formatNumber, titleCase } from "#lib/utils.js";
  import { PERSON_VALID_LABEL, personExclusionLabels, staffCategoryLabels } from "#lib/labels.js";
  import { autofocus } from "#lib/actions/focus.js";
  import Drawer from "#lib/components/Drawer.svelte";
  import { useDrawerEntity } from "#lib/composables/useDrawerEntity.svelte.js";
  import type { Person, IdFormState, PersonSearchResult } from "./types";
  import type { components } from "#lib/api/schema.js";
  import IdentifierEditor from "./IdentifierEditor.svelte";
  import Picker from "#lib/components/Picker.svelte";
  import NameFormsList from "./NameFormsList.svelte";
  import { formatCount } from "#lib/plural.js";

  type SharingPerson = components["schemas"]["SharingPersonOut"];
  type DistinctPerson = components["schemas"]["DistinctPersonOut"];
  type NameFormSummary = components["schemas"]["NameFormSummaryOut"];
  type PersonExclusion = components["schemas"]["PersonExclusion"];

  let {
    person,
    idForm,
    mergeActive,
    mergeSearch,
    onclose,
    onrename,
    onsetExclusion,
    onaddIdentifier,
    ontoggleIdForm,
    onsetIdentifierStatus,
    onopenDetach,
    onsetFormStatus,
    onmergeOpen,
    onmergeClose,
    onmerge,
    onabsorb,
    onunmarkDistinct,
    onopenPerson,
  }: {
    person: Person;
    idForm: IdFormState | null;
    mergeActive: boolean;
    mergeSearch: {
      query: string;
      loading: boolean;
      results: PersonSearchResult[];
      setQuery: (q: string) => void;
    };
    onclose: () => void;
    /** Renvoie true si le renommage a réussi (sinon l'édition reste ouverte). */
    onrename: (personId: number, lastName: string, firstName: string) => Promise<boolean>;
    onsetExclusion: (personId: number, exclusion: PersonExclusion | null) => void | Promise<void>;
    onaddIdentifier: (personId: number) => void | Promise<void>;
    ontoggleIdForm: (personId: number) => void;
    onsetIdentifierStatus: (identId: number, status: string) => void | Promise<void>;
    onopenDetach: (personId: number, nameForm: string) => void | Promise<void>;
    onsetFormStatus: (
      personId: number,
      nameForm: string,
      status: string,
    ) => void | Promise<void>;
    onmergeOpen: (personId: number) => void;
    onmergeClose: () => void;
    onmerge: (targetId: number, sourceId: number) => void | Promise<void>;
    /** Absorbe une autre personne dans celle du drawer (fusion vers `person`). */
    onabsorb: (otherId: number) => Promise<void>;
    /** Annule la décision qui déclare `person` et `otherId` distinctes. */
    onunmarkDistinct: (otherId: number) => Promise<void>;
    /** Ouvre le drawer d'une autre personne (depuis la liste des partages). */
    onopenPerson: (personId: number) => void;
  } = $props();

  let editing = $state(false);

  const details = useDrawerEntity({
    id: () => person.id,
    fetch: async (id) => {
      const [sharing, distinct, nameForms] = await Promise.all([
        api<SharingPerson[]>(`/api/persons/${id}/sharing-name-forms`),
        api<DistinctPerson[]>(`/api/persons/${id}/distinct-persons`),
        api<NameFormSummary[]>(`/api/persons/${id}/name-forms`),
      ]);
      return { sharing, distinct, nameForms };
    },
    onreset() {
      editing = false;
    },
  });
  // Personnes partageant ≥1 forme de nom (candidates à l'absorption).
  const sharing = $derived(details.data?.sharing ?? []);
  // Personnes déclarées distinctes de celle-ci.
  const distinct = $derived(details.data?.distinct ?? []);
  // Les formes de nom se chargent ici : la liste ne les porte pas, seul ce tiroir les montre. `null` tant qu'elles chargent.
  const nameForms = $derived(details.data?.nameForms ?? null);

  async function absorb(otherId: number) {
    await onabsorb(otherId);
    await details.reload();
  }

  async function unmarkDistinct(otherId: number) {
    await onunmarkDistinct(otherId);
    await details.reload();
  }

  let lastName = $state("");
  let firstName = $state("");

  function startEdit() {
    lastName = person.last_name;
    firstName = person.first_name;
    editing = true;
  }

  async function saveEdit() {
    if (await onrename(person.id, lastName, firstName)) editing = false;
  }

  // Échap annule d'abord l'édition du nom en cours.
  function onescape() {
    if (editing) editing = false;
    else onclose();
  }
</script>

<Drawer {onclose} {onescape}>
  {#snippet head()}
  <div class="drawer-head-row">
    {#if editing}
      <form class="drawer-edit" onsubmit={(e) => { e.preventDefault(); saveEdit(); }}>
        <input class="edit-input" bind:value={lastName} placeholder="Nom" aria-label="Nom" use:autofocus={{ select: true }} />
        <input class="edit-input" bind:value={firstName} placeholder="Prénom" aria-label="Prénom" />
        <button type="submit" class="btn btn-sm btn-primary">OK</button>
        <button type="button" class="btn btn-sm" onclick={() => (editing = false)}>Annuler</button>
      </form>
    {:else}
      <div class="drawer-title" class:excluded={!!person.exclusion}>
        <a
          class="drawer-name-link"
          href={resolve(`persons/${person.id}`)}
          target="_blank"
          rel="noopener"
          use:tooltip={'Voir la fiche publique'}
        >
          <span class="drawer-last">{titleCase(person.last_name)}</span>
          {titleCase(person.first_name)}
        </a>
        {#if person.has_rh}<RhCheck />{/if}
      </div>
      <div class="drawer-head-actions">
        <IconButton icon="edit" label="Modifier le nom" onclick={startEdit} />
        <select
          class="select exclusion-select"
          class:excluded={!!person.exclusion}
          use:tooltip={'Statut de la personne'}
          aria-label="Statut de la personne"
          value={person.exclusion ?? ""}
          onchange={(e) =>
            onsetExclusion(
              person.id,
              ((e.currentTarget as HTMLSelectElement).value || null) as PersonExclusion | null,
            )}
        >
          <option value="">{PERSON_VALID_LABEL}</option>
          {#each Object.entries(personExclusionLabels) as [value, label] (value)}
            <option {value}>{label}</option>
          {/each}
        </select>
      </div>
    {/if}
  </div>
  {/snippet}

    <div class="drawer-meta">
      <span>{formatCount(person.contribution_count ?? 0, "publication")}</span>
      <span>{formatNumber(person.in_perimeter_contribution_count ?? 0)} dans le périmètre</span>
      {#if person.exclusion}<span class="tag tag-pill tag-danger">{personExclusionLabels[person.exclusion]}</span>{/if}
    </div>

    {#if person.has_rh}
      <section class="drawer-section">
        <h3>Fiche RH</h3>
        <dl class="rh-info">
          {#if person.corps}
            <dt>Corps</dt>
            <dd>{person.corps}</dd>
          {/if}
          {#if person.staff_category}
            <dt>Catégorie</dt>
            <dd>{staffCategoryLabels[person.staff_category] ?? person.staff_category}</dd>
          {/if}
          {#if person.laboratories.length}
            <dt>{person.laboratories.every((lab) => lab.current) ? 'Laboratoire' : 'Dernier laboratoire'}</dt>
            <dd>{person.laboratories.map((lab) => lab.label).join(', ')}</dd>
          {/if}
        </dl>
      </section>
    {/if}

    <section class="drawer-section">
      <h3>Identifiants</h3>
      <IdentifierEditor
        {person}
        form={idForm}
        onadd={onaddIdentifier}
        ontoggleForm={ontoggleIdForm}
        onsetStatus={onsetIdentifierStatus}
      />
    </section>

    <section class="drawer-section">
      <h3>Formes de nom</h3>
      {#if nameForms === null}
        <span class="muted-small">Chargement…</span>
      {:else}
        <NameFormsList personId={person.id} {nameForms} onopenDetail={onopenDetach} onsetStatus={onsetFormStatus} />
      {/if}
    </section>

    {#if sharing.length}
      <section class="drawer-section">
        <h3>Personnes partageant une forme de nom</h3>
        <div class="sharing-list">
          {#each sharing as sp (sp.person_id)}
            <div class="sharing-row">
              {#if !sp.has_rh}
                <button
                  class="btn btn-sm"
                  use:tooltip={'Fusionner cette personne dans celle-ci'}
                  onclick={() => absorb(sp.person_id)}>Absorber</button
                >
              {/if}
              <button class="triage-person" onclick={() => onopenPerson(sp.person_id)}>
                <span class="person-last">{titleCase(sp.last_name)}</span>
                {titleCase(sp.first_name)}
              </button>
              {#if sp.has_rh}<RhCheck />{/if}
              <span class="muted-small" use:tooltip={sp.shared_forms.join(", ")}>
                {formatCount(sp.shared_forms.length, "forme")}
              </span>
            </div>
          {/each}
        </div>
      </section>
    {/if}

    {#if distinct.length}
      <section class="drawer-section">
        <h3>Distinct de</h3>
        <div class="sharing-list">
          {#each distinct as dp (dp.person_id)}
            <div class="sharing-row">
              <button
                class="btn btn-sm"
                use:tooltip={'Annuler la décision : les files de triage peuvent de nouveau présenter la paire'}
                onclick={() => unmarkDistinct(dp.person_id)}>Annuler</button
              >
              <button class="triage-person" onclick={() => onopenPerson(dp.person_id)}>
                <span class="person-last">{titleCase(dp.last_name)}</span>
                {titleCase(dp.first_name)}
              </button>
              {#if dp.has_rh}<RhCheck />{/if}
            </div>
          {/each}
        </div>
      </section>
    {/if}

    <section class="drawer-section">
      <h3>Fusion</h3>
      {#if mergeActive}
        <Picker
          floating
          minLength={2}
          placeholder="Nom à absorber"
          search={mergeSearch.query}
          onsearch={mergeSearch.setQuery}
          loading={mergeSearch.loading}
          results={mergeSearch.results}
          onpick={(r) => onmerge(person.id, r.id)}
          onclose={onmergeClose}
        >
          {#snippet item(r)}
            <strong>{r.last_name}</strong>
            {r.first_name}
            {#if r.current_unit}<span class="merge-dept">{r.current_unit}</span>{/if}
            {#if r.has_rh}<RhCheck />{/if}
          {/snippet}
        </Picker>
      {:else}
        <button class="btn btn-sm btn-dashed" onclick={() => onmergeOpen(person.id)}>Fusionner…</button>
      {/if}
    </section>
</Drawer>

<style>
  .merge-dept {
    font-size: var(--fs-sm);
    color: var(--muted);
    margin-left: 6px;
  }
  .drawer-title.excluded {
    text-decoration: line-through;
    opacity: 0.7;
  }
  .drawer-title {
    font-size: var(--fs-lg);
  }
  .drawer-last {
    font-weight: 600;
  }
  .edit-input {
    width: 128px;
  }
  .exclusion-select {
    height: 28px;
    font-size: var(--fs-sm);
    color: var(--muted);
  }
  .exclusion-select.excluded {
    color: var(--danger);
  }
  .rh-info {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 3px 12px;
    margin: 0;
    font-size: var(--fs-sm);
  }
  .rh-info dt {
    color: var(--muted);
  }
  .rh-info dd {
    margin: 0;
  }
  .sharing-list {
    display: flex;
    flex-direction: column;
    gap: 5px;
  }
  .sharing-row {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
</style>
