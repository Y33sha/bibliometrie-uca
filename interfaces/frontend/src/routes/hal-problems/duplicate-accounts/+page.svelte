<script lang="ts">
  import RhCheck from "#lib/components/RhCheck.svelte";
  import ListToolbar from "#lib/components/ListToolbar.svelte";
  import { withBase } from "#lib/paths.js";
  import PageHeader from "#lib/components/PageHeader.svelte";
  import { resolve } from "$app/paths";
  import { replaceQuery } from "#lib/url.js";
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
    void replaceQuery(resolve('hal-problems/duplicate-accounts'), p);
  }

  onMount(() => {
    const urlParams = new URLSearchParams(page.url.search);
    if (urlParams.get("page")) list.page = parseInt(urlParams.get("page")!) || 1;
    list.load();
  });
</script>

<PageHeader title="Comptes auteur HAL en double">
  Personnes liées à au moins deux personId distincts. Soit doublons d'auteurs, soit publications attribuées à un auteur homonyme.
</PageHeader>

<ListToolbar {list} one="personne" many="personnes" exportUrl={withBase("/api/hal-problems/duplicate-accounts/export.csv")} />

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
          <td>
            <div class="hal-accounts">
            {#each p.hal_accounts as ha}
              <div class="hal-account">
                <a href={halPersonUrl(ha.hal_person_id)} target="_blank" rel="noopener" class="id-badge">
                  {ha.hal_person_id}
                </a>
                <span class="hal-name">{ha.full_name}</span>
                <span class="hal-publications">{ha.publication_count} publication{ha.publication_count > 1 ? "s" : ""}</span>
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
            </div>
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
    font-size: var(--fs-md);
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
    font-size: var(--fs-sm);
    flex-wrap: wrap;
  }
  .hal-name {
    font-weight: 500;
  }
  .hal-publications {
    font-size: var(--fs-sm);
    color: var(--muted);
    background: var(--border-subtle);
    padding: 1px 6px;
    border-radius: var(--radius);
  }
  .hal-secondary-id {
    font-size: var(--fs-sm);
    color: var(--muted);
  }
</style>
