<script lang="ts">
  import { untrack } from "svelte";
  import { persons as personsApi } from "#lib/api/index.js";
  import { titleCase } from "#lib/utils.js";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
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

{#if !list.loaded}
  <div class="empty">Chargement…</div>
{:else if list.items.length === 0 && !list.loading}
  <div class="empty">Aucune forme ambiguë à trancher.</div>
{:else}
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
                <button
                  class="toggle-btn confirm"
                  class:active={p.status === "confirmed"}
                  title={p.status === "confirmed" ? "Retirer la confirmation" : "Confirmer"}
                  onclick={() =>
                    setStatus(
                      p.person_id,
                      form.name_form,
                      p.status === "confirmed" ? "pending" : "confirmed",
                    )}>&#x2713;</button
                >
                <button
                  class="toggle-btn reject"
                  title="Rejeter"
                  onclick={() => setStatus(p.person_id, form.name_form, "rejected")}
                  >&#x2717;</button
                >
              </span>
              {/if}
              <button class="triage-person" onclick={() => onopenPerson(p.person_id)}>
                <span class="triage-person-last">{titleCase(p.last_name)}</span>
                {titleCase(p.first_name)}
              </button>
              {#if p.has_rh}<span class="rh-check" title="Base RH">&#x2713;</span>{/if}
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
{/if}

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
