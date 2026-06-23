<script lang="ts">
  import { untrack } from "svelte";
  import { api, persons as personsApi } from "$lib/api";
  import { titleCase } from "$lib/utils";
  import Pagination from "$lib/components/Pagination.svelte";
  import type { components } from "$lib/api/schema";

  type AmbiguousNameFormsResponse = components["schemas"]["AmbiguousNameFormsResponse"];

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

  let page = $state(1);
  let data = $state<AmbiguousNameFormsResponse | null>(null);
  let loading = $state(false);

  async function load() {
    loading = true;
    data = await api<AmbiguousNameFormsResponse>(
      `/api/admin/ambiguous-name-forms?page=${page}&per_page=50`,
    );
    loading = false;
  }

  function handlePage(p: number) {
    page = p;
    load();
    window.scrollTo(0, 0);
  }

  async function setStatus(personId: number, nameForm: string, status: string) {
    await personsApi.updateNameFormStatus(
      personId,
      nameForm,
      status as "pending" | "confirmed" | "rejected",
    );
    await load();
    onchange();
  }

  // Charge au montage et à chaque incrément de `reloadKey` (action dans le drawer).
  // `untrack` autour de `load()` pour ne pas dépendre de `page`/`data`.
  $effect(() => {
    void reloadKey;
    untrack(load);
  });
</script>

<p class="intro">
  Formes de nom portées par <strong>plusieurs personnes</strong>, avec au moins un lien à
  valider. Une personne au nom <em>incompatible</em> avec la forme est probablement une
  erreur de rattachement (à rejeter) ; deux personnes compatibles sont soit des
  homonymes (à confirmer chacune), soit un doublon (à fusionner).
</p>

{#if data && data.forms.length === 0 && !loading}
  <div class="empty">Aucune forme ambiguë à trancher.</div>
{:else if data}
  <div class="forms">
    {#each data.forms as form (form.name_form)}
      <div class="form-block">
        <div class="form-head">
          <span class="form-name">{form.name_form}</span>
          <span class="form-count">{form.persons.length} personnes</span>
        </div>
        <div class="form-persons">
          {#each form.persons as p (p.person_id)}
            <div class="person-row" class:incompatible={!p.compatible}>
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
                  class:active={p.status === "rejected"}
                  title={p.status === "rejected" ? "Retirer le rejet" : "Rejeter"}
                  onclick={() =>
                    setStatus(
                      p.person_id,
                      form.name_form,
                      p.status === "rejected" ? "pending" : "rejected",
                    )}>&#x2717;</button
                >
              </span>
              <button class="person-link" onclick={() => onopenPerson(p.person_id)}>
                <span class="person-last">{titleCase(p.last_name)}</span>
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

  <Pagination {page} pages={data.pages} onchange={handlePage} />
{/if}

<style>
  .intro {
    font-size: 0.85rem;
    color: #555;
    margin: 4px 0 14px;
    max-width: 70ch;
  }
  .forms {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .form-block {
    border: 1px solid var(--border, #e0e0e0);
    border-radius: 6px;
    padding: 10px 12px;
  }
  .form-head {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-bottom: 6px;
  }
  .form-name {
    font-weight: 600;
    font-family: "SF Mono", SFMono-Regular, Consolas, "Liberation Mono", Menlo, monospace;
  }
  .form-count {
    font-size: 0.78rem;
    color: #888;
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
  .person-link {
    background: none;
    border: none;
    padding: 0;
    cursor: pointer;
    font: inherit;
    color: inherit;
    text-align: left;
  }
  .person-link:hover {
    color: #2563eb;
    text-decoration: underline;
  }
  .person-last {
    font-weight: 600;
  }
  .incompat-tag {
    font-size: 0.72rem;
    color: var(--danger, #c0392b);
    border: 1px solid var(--danger, #c0392b);
    border-radius: 3px;
    padding: 0 5px;
  }
  .empty {
    padding: 20px;
    color: #888;
  }
</style>
