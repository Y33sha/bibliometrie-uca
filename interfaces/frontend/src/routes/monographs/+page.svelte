<script lang="ts">
	import PageHeader from '#lib/components/PageHeader.svelte';
	import MonographsListView from '#lib/components/MonographsListView.svelte';
</script>

<PageHeader title="Monographies" hidden />

<MonographsListView apiKey="monographs-list" urlSync />
