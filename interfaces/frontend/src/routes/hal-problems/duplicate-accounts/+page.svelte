<script lang="ts">
  import { base } from "$app/paths";
  import { replaceState } from "$app/navigation";
  import { page as pageStore } from "$app/stores";
  import { onMount } from "svelte";
  import { api } from "$lib/api";
  import { titleCase } from "$lib/utils";
  import Pagination from "$lib/components/Pagination.svelte";

  import type { components } from "$lib/api/schema";
  type PersonRow = components["schemas"]["HalDuplicateAccountPerson"];
  type Response = components["schemas"]["HalDuplicateAccountsResponse"];

  let persons: PersonRow[] = $state([]);
  let total = $state(0);
  let page = $state(1);
  let pages = $state(1);
  let loading = $state(false);

  function syncUrl() {
    const p = new URLSearchParams();
    if (page > 1) p.set("page", String(page));
    const qs = p.toString();
    replaceState(`${base}/hal-problems/duplicate-accounts` + (qs ? "?" + qs : ""), {});
  }

  async function load() {
    loading = true;
    const data = await api<Response>(`/api/hal-problems/duplicate-accounts?page=${page}&per_page=50`);
    persons = data.persons;
    total = data.total;
    pages = data.pages;
    page = data.page;
    loading = false;
    syncUrl();
  }

  onMount(() => {
    const urlParams = new URLSearchParams($pageStore.url.search);
    if (urlParams.get("page")) page = parseInt(urlParams.get("page")!);
    load();
  });
</script>

<svelte:head>
  <title>Doublons comptes HAL — Bibliométrie UCA</title>
</svelte:head>

<h1>Doublons d'auteurs HAL</h1>

<div class="info-box">Personnes liées à au moins deux personId distincts. Soit doublons d'auteurs, soit publications attribuées à un auteur homonyme.</div>

<div class="toolbar">
  <span class="count">{total} personne{total > 1 ? "s" : ""}</span>
</div>

{#if loading}
  <div class="loading">Chargement...</div>
{:else if persons.length === 0}
  <div class="no-results">Aucun doublon détecté</div>
{:else}
  <table class="pub-table">
    <thead>
      <tr>
        <th>Personne</th>
        <th>Comptes HAL</th>
      </tr>
    </thead>
    <tbody>
      {#each persons as p}
        <tr>
          <td>
            <a href="{base}/persons/{p.person_id}" class="person-link">
              {titleCase(p.first_name)}
              {titleCase(p.last_name)}
            </a>
            {#if p.has_rh}<span class="rh-check" title="Fichier RH">&#10003;</span>{/if}
          </td>
          <td class="hal-accounts">
            {#each p.hal_accounts as ha}
              <div class="hal-account">
                <a href="https://hal.science/search/index/?qa%5BauthIdHal_i%5D%5B%5D={ha.hal_person_id}" target="_blank" rel="noopener" class="hal-id">
                  {ha.hal_person_id}
                </a>
                <span class="hal-name">{ha.full_name}</span>
                <span class="hal-pubs">{ha.pub_count} publi{ha.pub_count > 1 ? "s" : ""}</span>
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
    {page}
    {pages}
    onchange={(p) => {
      page = p;
      syncUrl();
      load();
      window.scrollTo(0, 0);
    }}
  />
{/if}

<style>
  .count {
    font-size: 0.9rem;
  }
  .pub-table {
    width: 100%;
    border-collapse: collapse;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
  }
  .pub-table thead th {
    background: #f5f4f1;
    padding: 8px 12px;
    text-align: left;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--muted);
    border-bottom: 2px solid var(--border);
  }
  .pub-table tbody tr {
    border-bottom: 1px solid #f0efec;
  }
  .pub-table tbody tr:hover {
    background: #fafaf8;
  }
  .pub-table td {
    padding: 8px 12px;
    font-size: 0.9rem;
    vertical-align: top;
  }
  .person-link {
    color: var(--accent);
    text-decoration: none;
    font-weight: 500;
  }
  .person-link:hover {
    text-decoration: underline;
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
    font-family: monospace;
    font-size: 0.8rem;
  }
  .hal-id:hover {
    text-decoration: underline;
  }
  .hal-name {
    font-weight: 500;
  }
  .hal-pubs {
    font-size: 0.8rem;
    color: var(--muted);
    background: #f0efec;
    padding: 1px 6px;
    border-radius: 3px;
  }
  .hal-secondary-id {
    font-size: 0.8rem;
    color: var(--muted);
  }
</style>
