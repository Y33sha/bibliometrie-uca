<script lang="ts">
	import { sectionLabels } from '#lib/labels.js';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
</script>

<PageHeader title={sectionLabels.monographs} hidden />

<MonographsListView apiKey="monographs-list" urlSync />
