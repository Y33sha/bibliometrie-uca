<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import cloud from 'd3-cloud';
	import type { components } from '#lib/api/schema.js';

	type SubjectFrequency = components['schemas']['SubjectFrequency'];

	interface CloudWord extends cloud.Word {
		id: number;
		/** Rang du sujet entre le moins et le plus fréquent, de 0 à 1, sur une échelle logarithmique. */
		weight: number;
	}

	// Nuage des sujets les plus fréquents : la taille et la teinte d'un mot croissent avec le nombre de publications. Chaque mot mène à la fiche du sujet.
	let { subjects }: { subjects: SubjectFrequency[] } = $props();

	const MIN_SIZE = 11;
	const MAX_SIZE = 32;
	// Teinte d'un mot : de la plus claire (sujet le moins fréquent) au bleu-vert du site (le plus fréquent).
	const wordColor = (weight: number) =>
		`color-mix(in srgb, var(--accent) ${Math.round(45 + weight * 55)}%, var(--accent-soft))`;

	let container: HTMLDivElement | undefined = $state();
	let width = $state(800);
	let height = $state(420);

	function weightFor(count: number, minCount: number, maxCount: number): number {
		if (maxCount === minCount) return 0.5;
		return (
			(Math.log10(count + 1) - Math.log10(minCount + 1)) /
			(Math.log10(maxCount + 1) - Math.log10(minCount + 1))
		);
	}

	let placedWords = $state<CloudWord[]>([]);
	let layoutDone = $state(false);

	function buildLayout() {
		if (!subjects.length) {
			placedWords = [];
			layoutDone = true;
			return;
		}
		const counts = subjects.map((s) => s.count);
		const minCount = Math.min(...counts);
		const maxCount = Math.max(...counts);
		const words: CloudWord[] = subjects.map((s) => {
			const weight = weightFor(s.count, minCount, maxCount);
			return { text: s.label, size: MIN_SIZE + weight * (MAX_SIZE - MIN_SIZE), id: s.id, weight };
		});

		layoutDone = false;
		cloud<CloudWord>()
			.size([width, height])
			.words(words)
			.padding(3)
			// Texte horizontal uniquement, plus lisible.
			.rotate(() => 0)
			.font('system-ui, sans-serif')
			.fontSize((d) => d.size!)
			.spiral('archimedean')
			.on('end', (placed: CloudWord[]) => {
				placedWords = placed;
				layoutDone = true;
			})
			.start();
	}

	function onResize() {
		if (container) {
			const rect = container.getBoundingClientRect();
			width = Math.max(300, rect.width);
			// Tous les mots sont horizontaux : une hauteur compacte suffit.
			height = Math.max(180, Math.round(rect.width * 0.4));
		}
		buildLayout();
	}

	$effect(() => {
		void subjects;
		if (container) buildLayout();
	});

	onMount(() => {
		onResize();
		const ro = new ResizeObserver(() => onResize());
		if (container) ro.observe(container);
		return () => ro.disconnect();
	});
</script>

<div bind:this={container} class="cloud-container">
	{#if subjects.length === 0}
		<p class="empty">Aucun sujet à afficher.</p>
	{:else}
		<svg {width} {height} viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet">
			<g transform="translate({width / 2}, {height / 2})">
				{#each placedWords as w (w.id)}
					<a href={resolve(`subjects/${w.id}`)}>
						<text
							text-anchor="middle"
							font-family="system-ui, sans-serif"
							font-size={w.size}
							style:fill={wordColor(w.weight)}
							transform={`translate(${w.x ?? 0}, ${w.y ?? 0})`}
						>
							{w.text}
						</text>
					</a>
				{/each}
			</g>
		</svg>
		{#if !layoutDone}
			<p class="layout-loading">Mise en page…</p>
		{/if}
	{/if}
</div>

<style>
	.cloud-container {
		width: 100%;
		overflow: hidden;
	}
	svg {
		display: block;
		width: 100%;
		height: auto;
	}
	/* Le survol atténue le mot, sans le souligner. */
	a,
	a:hover {
		text-decoration: none;
	}
	text {
		cursor: pointer;
		transition: opacity 0.15s;
	}
	text:hover {
		opacity: 0.7;
	}
	.empty,
	.layout-loading {
		color: var(--muted);
		font-style: italic;
		font-size: 0.9rem;
		margin: 0;
		padding: 12px;
	}
</style>
