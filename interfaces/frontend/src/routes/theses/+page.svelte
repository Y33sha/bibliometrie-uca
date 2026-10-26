<script lang="ts">
  import { pageTitle } from "#lib/institution.svelte.js";
  import ThesesListView from "#lib/components/ThesesListView.svelte";
</script>

<svelte:head><title>{pageTitle("Thèses")}</title></svelte:head>

<h1 class="visually-hidden">Thèses</h1>

<ThesesListView apiKey="theses-list" basePath="/theses" />
