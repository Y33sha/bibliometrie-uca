<script lang="ts">
  import PageHeader from "#lib/components/PageHeader.svelte";
  import ThesesListView from "#lib/components/ThesesListView.svelte";
</script>

<PageHeader title="Thèses" hidden />

<ThesesListView apiKey="theses-list" basePath="/theses" />
