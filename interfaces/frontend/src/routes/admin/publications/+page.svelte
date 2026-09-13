<script lang="ts">
  import { pageTitle } from "$lib/institution.svelte";
  import HubTabs from "$lib/components/HubTabs.svelte";
  import PublicationsListView from "$lib/components/PublicationsListView.svelte";

  // Onglets du référentiel : la liste, puis les files de détection des fusions suspectes.
  let tab = $state("all");
</script>

<svelte:head>
  <title>{pageTitle("Admin - Publications")}</title>
</svelte:head>

<HubTabs
  tabs={[{ key: "all", label: "Toutes les publications" }]}
  active={tab}
  onselect={(key) => (tab = key)}
/>

{#if tab === "all"}
  <PublicationsListView restrictToPublications basePath="/admin/publications" />
{/if}
