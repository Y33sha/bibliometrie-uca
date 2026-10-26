<script lang="ts">
  import RhCheck from "#lib/components/RhCheck.svelte";
  import ResultCount from "#lib/components/ResultCount.svelte";
  import { pageTitle } from "#lib/institution.svelte.js";
  import { resolve } from "$app/paths";
  import { replaceState } from "$app/navigation";
  import { page } from "$app/state";
  import { onMount } from "svelte";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
  import { halPersonUrl, titleCase } from "#lib/utils.js";
  import ListStatus from "#lib/components/ListStatus.svelte";
  import Pagination from "#lib/components/Pagination.svelte";

  import type { components } from "#lib/api/schema.js";
  type PersonRow = components["schemas"]["HalDuplicateAccountPerson"];

  const list = usePaginatedFetch<PersonRow>({
    endpoint: "/api/hal-problems/duplicate-accounts",
    itemsKey: "persons",
    apiKey: "hal-duplicate-accounts",
    buildParams: () => new URLSearchParams(),
  });

  function syncUrl() {
    const p = new URLSearchParams();
    if (list.page > 1) p.set("page", String(list.page));
    const qs = p.toString();
    replaceState(resolve('hal-problems/duplicate-accounts') + (qs ? "?" + qs : ""), {});
  }

  onMount(() => {
    const urlParams = new URLSearchParams(page.url.search);
    if (urlParams.get("page")) list.page = parseInt(urlParams.get("page")!) || 1;
    list.load();
  });
</script>

<svelte:head>
  <title>{pageTitle("Doublons comptes HAL")}</title>
</svelte:head>

<h1>Doublons d'auteurs HAL</h1>

<div class="info-box">Personnes liées à au moins deux personId distincts. Soit doublons d'auteurs, soit publications attribuées à un auteur homonyme.</div>

<div class="toolbar">
  <ResultCount {list} one="personne" many="personnes" />
</div>

<ListStatus {list} emptyText="Aucun doublon détecté">
  <table class="data-table">
    <thead>
      <tr>
        <th>Personne</th>
        <th>Comptes HAL</th>
      </tr>
    </thead>
    <tbody>
      {#each list.items as p}
        <tr>
          <td>
            <a href={resolve(`persons/${p.person_id}`)} class="entity-link">
              {titleCase(p.first_name)}
              {titleCase(p.last_name)}
            </a>
            {#if p.has_rh}<RhCheck />{/if}
          </td>
          <td class="hal-accounts">
            {#each p.hal_accounts as ha}
              <div class="hal-account">
                <a href={halPersonUrl(ha.hal_person_id)} target="_blank" rel="noopener" class="hal-id">
                  {ha.hal_person_id}
                </a>
                <span class="hal-name">{ha.full_name}</span>
                <span class="hal-publications">{ha.publication_count} publi{ha.publication_count > 1 ? "s" : ""}</span>
                {#if ha.idhal}
                  <span class="hal-secondary-id">idHAL: {ha.idhal}</span>
                {/if}
                {#if ha.orcid}
                  <span class="hal-secondary-id">ORCID: {ha.orcid}</span>
                {/if}
                {#if ha.idref}
                  <span class="hal-secondary-id">IdRef: {ha.idref}</span>
                {/if}
              </div>
            {/each}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>

  <Pagination
    page={list.page}
    pages={list.pages}
    onchange={(p) => {
      list.goToPage(p);
      syncUrl();
    }}
  />
</ListStatus>

<style>
  .data-table td {
    font-size: 0.9rem;
  }
  .hal-accounts {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .hal-account {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 0.85rem;
    flex-wrap: wrap;
  }
  .hal-id {
    color: var(--accent);
    text-decoration: none;
    font-family: var(--mono);
    font-size: 0.8rem;
  }
  .hal-id:hover {
    text-decoration: underline;
  }
  .hal-name {
    font-weight: 500;
  }
  .hal-publications {
    font-size: 0.8rem;
    color: var(--muted);
    background: var(--border-subtle);
    padding: 1px 6px;
    border-radius: var(--radius);
  }
  .hal-secondary-id {
    font-size: 0.8rem;
    color: var(--muted);
  }
</style>
