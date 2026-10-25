<script lang="ts">
	import { resolve } from '$app/paths';
	import type { components } from '#lib/api/schema.js';

	type SubjectFrequency = components['schemas']['SubjectFrequency'];

	// Sujets les plus fréquents en barres horizontales, longueur proportionnelle au nombre de publications.
	let { subjects, limit = 15 }: { subjects: SubjectFrequency[]; limit?: number } = $props();

	const top = $derived([...subjects].sort((a, b) => b.count - a.count).slice(0, limit));
	const max = $derived(top[0]?.count ?? 1);
</script>

<ol class="subject-bars">
	{#each top as s (s.id)}
		<li>
			<a class="subject-label" href={resolve(`subjects/${s.id}`)} title={s.label}>{s.label}</a>
			<span class="bar-track"><span class="bar" style="width: {(s.count / max) * 100}%"></span></span>
			<span class="subject-count">{s.count.toLocaleString('fr-FR')}</span>
		</li>
	{/each}
</ol>

<style>
	.subject-bars {
		margin: 0;
		padding: 0;
		list-style: none;
		display: flex;
		flex-direction: column;
		gap: 8px;
	}
	li {
		display: grid;
		grid-template-columns: minmax(120px, 280px) 1fr 3.5em;
		align-items: center;
		gap: 12px;
		font-size: 0.9rem;
	}
	.subject-label {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		text-align: right;
	}
	.bar-track {
		display: block;
		height: 12px;
	}
	.bar {
		display: block;
		height: 100%;
		min-width: 2px;
		border-radius: 0 var(--radius) var(--radius) 0;
		background: var(--accent-mid);
	}
	.subject-count {
		font-size: 0.8rem;
		color: var(--text-secondary);
	}
</style>
