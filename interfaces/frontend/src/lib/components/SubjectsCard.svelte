<script lang="ts">
	import { onMount } from 'svelte';
	import { api, errorMessage } from '#lib/api/index.js';
	import type { components } from '#lib/api/schema.js';
	import ListStatus from '#lib/components/ListStatus.svelte';
	import SubjectsCloud from '#lib/components/SubjectsCloud.svelte';

	type SubjectFrequency = components['schemas']['SubjectFrequency'];

	// Carte « Sujets principaux » d'un tableau de bord d'entité : nuage des sujets les plus fréquents de ses publications.
	let {
		endpoint,
	}: {
		/** Route des sujets de l'entité, par exemple `/api/serials/12/subjects`. */
		endpoint: string;
	} = $props();

	const LIMIT = 30;

	let subjects: SubjectFrequency[] = $state([]);
	let loading = $state(true);
	let error: string | null = $state(null);

	onMount(async () => {
		try {
			subjects = await api<SubjectFrequency[]>(`${endpoint}?limit=${LIMIT}`, { key: 'entity-subjects' });
		} catch (e) {
			error = errorMessage(e);
		} finally {
			loading = false;
		}
	});
</script>

<div class="dash-card">
	<h2>Sujets principaux</h2>
	<ListStatus list={{ loading, error, items: subjects }} emptyText="Aucun sujet">
		<SubjectsCloud {subjects} />
	</ListStatus>
</div>
