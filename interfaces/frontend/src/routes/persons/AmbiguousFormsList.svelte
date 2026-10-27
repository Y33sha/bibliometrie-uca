<script lang="ts">
  import RhCheck from "#lib/components/RhCheck.svelte";
  import StatusToggles from "#lib/components/StatusToggles.svelte";
  import { untrack } from "svelte";
  import { persons as personsApi } from "#lib/api/index.js";
  import { titleCase } from "#lib/utils.js";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
  import ListStatus from "#lib/components/ListStatus.svelte";
  import Pagination from "#lib/components/Pagination.svelte";
  import type { components } from "#lib/api/schema.js";

  type AmbiguousNameForm = components["schemas"]["AmbiguousNameFormOut"];

  let {
    onopenPerson,
    onchange,
    reloadKey,
  }: {
    /** Ouvre le drawer d'une personne. */
    onopenPerson: (personId: number) => void;
    /** Notifie le parent après une mutation (rafraîchir le badge de l'onglet). */
    onchange: () => void;
    /** Incrémenté par le parent après une action dans le drawer → recharge la file. */
    reloadKey: number;
  } = $props();

  const list = usePaginatedFetch<AmbiguousNameForm>({
    endpoint: "/api/persons/ambiguous-name-forms",
    itemsKey: "forms",
    apiKey: "ambiguous-name-forms",
    buildParams: () => new URLSearchParams(),
    pageParam: null,
  });

  async function setStatus(personId: number, nameForm: string, status: string) {
    await personsApi.updateNameFormStatus(
      personId,
      nameForm,
      status as "pending" | "confirmed" | "rejected",
    );
    await list.load();
    onchange();
  }

  // Charge au montage et à chaque incrément de `reloadKey` (action dans le drawer).
  // `untrack` autour de `list.load()` pour ne pas dépendre de l'état de la liste.
  $effect(() => {
    void reloadKey;
    untrack(list.load);
  });
</script>

<p class="triage-intro">
  Formes de nom portées par <strong>plusieurs personnes</strong>, avec au moins un lien à
  valider. Une personne au nom <em>incompatible</em> avec la forme est probablement une
  erreur de rattachement (à rejeter) ; deux personnes compatibles sont soit des
  homonymes (à confirmer chacune), soit un doublon (à fusionner).
</p>

<ListStatus {list} emptyText="Aucune forme ambiguë à trancher.">
  <div class="triage-list">
    {#each list.items as form (form.name_form)}
      <div class="triage-item">
        <div class="form-head">
          <span class="form-name">{form.name_form}</span>
          <span class="form-count">{form.persons.length} personnes</span>
        </div>
        <div class="form-persons">
          {#each form.persons as p (p.person_id)}
            <div class="person-row" class:incompatible={!p.compatible}>
              {#if p.canonical}
                <span class="canonical-tag" title="Forme dérivée du nom de la personne, confirmée d'office"
                  >nom</span
                >
              {:else}
              <span class="chip-controls">
                <StatusToggles status={p.status} onchange={(s) => setStatus(p.person_id, form.name_form, s)} />
              </span>
              {/if}
              <button class="triage-person" onclick={() => onopenPerson(p.person_id)}>
                <span class="triage-person-last">{titleCase(p.last_name)}</span>
                {titleCase(p.first_name)}
              </button>
              {#if p.has_rh}<RhCheck />{/if}
              {#if !p.compatible}
                <span class="incompat-tag" title="Nom canonique incompatible avec la forme">
                  incompatible
                </span>
              {/if}
            </div>
          {/each}
        </div>
      </div>
    {/each}
  </div>

  <Pagination page={list.page} pages={list.pages} onchange={list.goToPage} />
</ListStatus>

<style>
  .form-head {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 6px;
  }
  .form-name {
    font-weight: 600;
    font-family: var(--mono);
  }
  .form-count {
    font-size: 0.78rem;
    color: var(--muted);
  }
  .form-persons {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .person-row {
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }
  .incompat-tag {
    font-size: 0.72rem;
    color: var(--danger);
    border: 1px solid var(--danger);
    border-radius: var(--radius);
    padding: 0 5px;
  }
</style>
