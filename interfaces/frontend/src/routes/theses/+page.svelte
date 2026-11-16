<script lang="ts">
  import { sectionLabels } from "#lib/labels.js";
  import PageHeader from "#lib/components/PageHeader.svelte";
  import ThesesListView from "#lib/components/ThesesListView.svelte";
</script>

<PageHeader title={sectionLabels.theses} hidden />

<ThesesListView apiKey="theses-list" basePath="/theses" />
