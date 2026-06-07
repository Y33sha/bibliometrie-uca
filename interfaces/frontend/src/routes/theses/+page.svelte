<script lang="ts">
  import ThesesListView from "$lib/components/ThesesListView.svelte";
</script>

<svelte:head><title>Thèses — Bibliométrie UCA</title></svelte:head>

<ThesesListView apiKey="theses-list" basePath="/theses" />
