<script lang="ts">
  import PageHeader from "#lib/components/PageHeader.svelte";
  import ListToolbar from "#lib/components/ListToolbar.svelte";
  import SortChevron from "#lib/components/SortChevron.svelte";
  import { onMount } from "svelte";
  import { resolve } from "$app/paths";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
  import { withBase } from "#lib/paths.js";
  import { nextSort, sortDirection } from "#lib/sort.js";
  import { paramsToQuery } from "#lib/utils.js";
  import ListStatus from "#lib/components/ListStatus.svelte";
  import Pagination from "#lib/components/Pagination.svelte";
  import type { components } from "#lib/api/schema.js";

  type SubjectListItem = components["schemas"]["SubjectListItem"];

  let search = $state("");
  let currentSort = $state("publications_desc");
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  function buildParams(): URLSearchParams {
    const params = new URLSearchParams();
    const q = search.trim();
    if (q) params.set("search", q);
    params.set("sort", currentSort);
    return params;
  }

  const list = usePaginatedFetch<SubjectListItem>({
    endpoint: "/api/subjects",
    itemsKey: "items",
    apiKey: "subjects",
    pageParam: null,
    buildParams,
  });

  const exportUrl = $derived(withBase(`/api/subjects/export.csv?${paramsToQuery(buildParams())}`));

  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      list.page = 1;
      list.load();
    }, 300);
  }

  function setSort(column: "label" | "publications") {
    currentSort = nextSort(currentSort, column, column === "label" ? "asc" : "desc");
    list.page = 1;
    list.load();
  }

  onMount(() => {
    list.load();
  });
</script>

<PageHeader title="Sujets" hidden />

<ListToolbar bind:search placeholder="Rechercher dans les libellés" onsearch={onSearchInput} {list} one="sujet" many="sujets" {exportUrl} />

<ListStatus {list} emptyText="Aucun sujet ne correspond à ces critères.">
  <table class="data-table">
    <thead>
      <tr>
        <th class="sortable" onclick={() => setSort("label")}>Libellé <SortChevron direction={sortDirection(currentSort, "label")} /></th>
        <th class="num sortable" onclick={() => setSort("publications")}>Occurrences <SortChevron direction={sortDirection(currentSort, "publications")} /></th>
      </tr>
    </thead>
    <tbody>
      {#each list.items as s (s.id)}
        <tr>
          <td>
            <a href={resolve(`subjects/${s.id}`)}>{s.label}</a>
          </td>
          <td class="num">{s.usage_count.toLocaleString("fr-FR")}</td>
        </tr>
      {/each}
    </tbody>
  </table>

  <Pagination page={list.page} pages={list.pages} onchange={list.goToPage} />
</ListStatus>
