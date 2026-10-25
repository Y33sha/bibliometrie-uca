<script lang="ts">
  import { pageTitle } from "#lib/institution.svelte.js";
  import { resolve } from "$app/paths";
  import { replaceState } from "$app/navigation";
  import { page } from "$app/state";
  import { onMount } from "svelte";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
  import { halPersonUrl, titleCase } from "#lib/utils.js";
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
  <span class="count">{list.total} personne{list.total > 1 ? "s" : ""}</span>
</div>

{#if list.loading}
  <div class="loading">Chargement…</div>
{:else if list.items.length === 0}
  <div class="no-results">Aucun doublon détecté</div>
{:else}
  <table class="publication-table">
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
            <a href={resolve(`persons/${p.person_id}`)} class="person-link">
              {titleCase(p.first_name)}
              {titleCase(p.last_name)}
            </a>
            {#if p.has_rh}<span class="rh-check" title="Fichier RH">&#10003;</span>{/if}
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
{/if}

<style>
  .count {
    font-size: 0.9rem;
  }
  .publication-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .publication-table thead th {
    background: var(--surface);
    padding: 8px 12px;
    text-align: left;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--muted);
    border-bottom: 2px solid var(--border);
  }
  .publication-table tbody tr {
    border-bottom: 1px solid var(--border-subtle);
  }
  .publication-table tbody tr:hover {
    background: var(--surface-hover);
  }
  .publication-table td {
    padding: 8px 12px;
    font-size: 0.9rem;
    vertical-align: top;
  }
  .person-link {
    font-weight: 500;
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
