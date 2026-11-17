<script lang="ts">
	import { sectionLabels } from '#lib/labels.js';
	import PageHeader from '#lib/components/PageHeader.svelte';
	import PublishersListView from '#lib/components/PublishersListView.svelte';
</script>

<PageHeader title={sectionLabels.publishers} hidden />

<PublishersListView urlSync />
