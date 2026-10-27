<script lang="ts">
  import PageHeader from "#lib/components/PageHeader.svelte";
  import ListToolbar from "#lib/components/ListToolbar.svelte";
  import { onMount } from "svelte";
  import { resolve } from "$app/paths";
  import { usePaginatedFetch } from "#lib/composables/usePaginatedFetch.svelte.js";
  import ListStatus from "#lib/components/ListStatus.svelte";
  import Pagination from "#lib/components/Pagination.svelte";
  import type { components } from "#lib/api/schema.js";

  type SubjectListItem = components["schemas"]["SubjectListItem"];

  let search = $state("");
  let minCount = $state(3);
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  const list = usePaginatedFetch<SubjectListItem>({
    endpoint: "/api/subjects",
    itemsKey: "items",
    apiKey: "subjects",
    pageParam: null,
    buildParams() {
      const params = new URLSearchParams();
      const q = search.trim();
      if (q) params.set("search", q);
      params.set("min_count", String(minCount));
      return params;
    },
  });

  function onSearchInput() {
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      list.page = 1;
      list.load();
    }, 300);
  }

  function onMinCountChange() {
    list.page = 1;
    list.load();
  }

  onMount(() => {
    list.load();
  });
</script>

<PageHeader title="Sujets" hidden />

<ListToolbar bind:search placeholder="Rechercher dans les libellés" onsearch={onSearchInput} {list} one="sujet" many="sujets">
  {#snippet filters()}
    <label class="min-count">
      Occurrences minimales
      <input type="number" min="1" bind:value={minCount} onchange={onMinCountChange} />
    </label>
  {/snippet}
</ListToolbar>

<ListStatus {list} emptyText="Aucun sujet ne correspond à ces critères.">
  <table class="data-table">
    <thead>
      <tr>
        <th>Libellé</th>
        <th class="num">Occurrences</th>
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

<style>
  .min-count {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding-left: 10px;
    font-size: 0.9rem;
    white-space: nowrap;
  }
  .min-count input {
    width: 70px;
  }
</style>
