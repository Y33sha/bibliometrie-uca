<script lang="ts">
  import PageHeader from "#lib/components/PageHeader.svelte";
  import ListToolbar from "#lib/components/ListToolbar.svelte";
  import SortChevron from "#lib/components/SortChevron.svelte";
  import ActiveFilterBar from "#lib/components/ActiveFilterBar.svelte";
  import FilterLayout from "#lib/components/filters/FilterLayout.svelte";
  import FilterPanel from "#lib/components/filters/FilterPanel.svelte";
  import FilterPanelToggle from "#lib/components/filters/FilterPanelToggle.svelte";
  import { onMount } from "svelte";
  import { resolve } from "$app/paths";
  import { useFacets } from "#lib/composables/useFacets.svelte.js";
  import { useFilteredList } from "#lib/composables/useFilteredList.svelte.js";
  import { facetDefs } from "#lib/filterRegistry.js";
  import { subjectVocabularyLabels } from "#lib/labels.js";
  import { withBase } from "#lib/paths.js";
  import { nextSort, sortDirection } from "#lib/sort.js";
  import { SUBJECT_FILTER_GROUPS, SUBJECT_FILTERS } from "#lib/subjectFilters.js";
  import { paramsToQuery } from "#lib/utils.js";
  import ListStatus from "#lib/components/ListStatus.svelte";
  import Pagination from "#lib/components/Pagination.svelte";
  import type { components } from "#lib/api/schema.js";

  type SubjectListItem = components["schemas"]["SubjectListItem"];

  const list = useFilteredList<SubjectListItem, ReturnType<typeof useFacets>>({
    filters: SUBJECT_FILTERS,
    endpoint: "/api/subjects",
    itemsKey: "items",
    perPage: 50,
    apiKey: () => "subjects",
    defaultSort: "publications_desc",
    urlSync: () => true,
    basePath: () => "/subjects",
    debounceMs: 300,
    facets: (buildParams) =>
      useFacets({
        endpoint: "/api/subjects/facets",
        apiKey: "subjects-facets",
        buildParams,
        facets: facetDefs(SUBJECT_FILTERS),
      }),
  });

  const exportUrl = $derived.by(() => {
    const params = list.filterParams();
    params.set("sort", list.sort);
    return withBase(`/api/subjects/export.csv?${paramsToQuery(params)}`);
  });

  function setSort(column: "label" | "publications") {
    list.setSort(nextSort(list.sort, column, column === "label" ? "asc" : "desc"));
  }

  onMount(list.restore);
</script>

<PageHeader title="Sujets" hidden />

<ListToolbar bind:search={list.search} placeholder="Rechercher dans les libellés" onsearch={list.onSearchInput} list={list.listing} one="sujet" many="sujets" {exportUrl} countBelow>
  {#snippet leading()}
    <FilterPanelToggle bind:open={list.panel.open} active={list.activeCount} />
  {/snippet}
  {#snippet activeFilters()}
    <ActiveFilterBar filters={SUBJECT_FILTERS} bind:values={list.values} options={list.facets.options} onchange={list.onFilterChange} />
  {/snippet}
</ListToolbar>

<FilterLayout bind:open={list.panel.open}>
  {#snippet panel()}
    <FilterPanel filters={SUBJECT_FILTERS} groups={SUBJECT_FILTER_GROUPS} bind:values={list.values} options={list.facets.options} presenceCounts={{}} loaded={list.facets.loaded} entityEndpoint="/api/subjects/facets" buildParams={list.filterParams} panel={list.panel} onchange={list.onFilterChange} />
  {/snippet}

  <ListStatus list={list.listing} emptyText="Aucun sujet ne correspond à ces critères.">
    <table class="data-table">
      <thead>
        <tr>
          <th class="sortable" onclick={() => setSort("label")}>Libellé <SortChevron direction={sortDirection(list.sort, "label")} /></th>
          <th>Vocabulaires</th>
          <th class="num sortable" onclick={() => setSort("publications")}>Occurrences <SortChevron direction={sortDirection(list.sort, "publications")} /></th>
        </tr>
      </thead>
      <tbody>
        {#each list.listing.items as s (s.label_normalized)}
          <tr>
            <td>
              <a href={resolve(`subjects/${s.label_normalized}`)}>{s.label}</a>
            </td>
            <td class="muted">{s.vocabularies.map((v) => subjectVocabularyLabels[v]).join(", ")}</td>
            <td class="num">{s.usage_count.toLocaleString("fr-FR")}</td>
          </tr>
        {/each}
      </tbody>
    </table>

    <Pagination page={list.listing.page} pages={list.listing.pages} onchange={list.goToPage} />
  </ListStatus>
</FilterLayout>
