<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/stores";
  import { pageTitle } from "$lib/institution.svelte";
  import HubTabs from "$lib/components/HubTabs.svelte";
  import PublicationsListView from "$lib/components/PublicationsListView.svelte";
  import PublicationDrawer from "./PublicationDrawer.svelte";

  // Onglets du référentiel : la liste, puis les files de détection des fusions suspectes.
  let tab = $state("all");

  // Volet d'une publication : ouvert tant que `?publication=<id>` figure dans l'URL.
  const selectedPublicationId = $derived(
    Number($page.url.searchParams.get("publication")) || null,
  );

  function selectPublication(id: number | null) {
    const url = new URL($page.url);
    if (id === null) url.searchParams.delete("publication");
    else url.searchParams.set("publication", String(id));
    void goto(url, { replaceState: true, noScroll: true, keepFocus: true });
  }
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
  <PublicationsListView
    restrictToPublications
    basePath="/admin/publications"
    activePublicationId={selectedPublicationId}
    onopenPublication={selectPublication}
  />
{/if}

{#if selectedPublicationId !== null}
  <PublicationDrawer
    publicationId={selectedPublicationId}
    onclose={() => selectPublication(null)}
  />
{/if}
