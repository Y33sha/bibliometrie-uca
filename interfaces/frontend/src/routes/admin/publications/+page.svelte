<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { pageTitle } from "#lib/institution.svelte.js";
  import HubTabs from "#lib/components/HubTabs.svelte";
  import PublicationsListView from "#lib/components/PublicationsListView.svelte";
  import PublicationDrawer from "./PublicationDrawer.svelte";
  import SuspectMergesList from "./SuspectMergesList.svelte";
  import { api } from "#lib/api/index.js";

  // Onglets du référentiel : la liste, puis les files de détection des fusions suspectes.
  let tab = $state("all");
  let suspectMergeCount = $state(0);

  $effect(() => {
    void api<{ total: number }>("/api/publications/suspect-merges/count").then(
      (data) => (suspectMergeCount = data.total),
    );
  });

  // Volet d'une publication : ouvert tant que `?publication=<id>` figure dans l'URL.
  const selectedPublicationId = $derived(
    Number(page.url.searchParams.get("publication")) || null,
  );

  function selectPublication(id: number | null) {
    const url = new URL(page.url.href);
    if (id === null) url.searchParams.delete("publication");
    else url.searchParams.set("publication", String(id));
    void goto(url, { replaceState: true, reset: false });
  }
</script>

<svelte:head>
  <title>{pageTitle("Admin - Publications")}</title>
</svelte:head>

<HubTabs
  tabs={[
    { key: "all", label: "Toutes les publications" },
    { key: "suspect-merges", label: "Fusions suspectes", count: suspectMergeCount },
  ]}
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

{#if tab === "suspect-merges"}
  <SuspectMergesList
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
