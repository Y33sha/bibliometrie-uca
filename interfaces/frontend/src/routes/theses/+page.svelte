<script lang="ts">
  import { pageTitle } from "$lib/institution.svelte";
  import ThesesListView from "$lib/components/ThesesListView.svelte";
</script>

<svelte:head><title>{pageTitle("Thèses")}</title></svelte:head>

<ThesesListView apiKey="theses-list" basePath="/theses" />
