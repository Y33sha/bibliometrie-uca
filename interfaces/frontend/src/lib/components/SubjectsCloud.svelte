<script lang="ts">
	import { onMount } from 'svelte';
	import { resolve } from '$app/paths';
	import cloud from 'd3-cloud';
	import { cssColor } from '#lib/components/charts/cssVar.js';
	import { mixColors } from '#lib/components/charts/contrast.js';
	import type { components } from '#lib/api/schema.js';

	type SubjectFrequency = components['schemas']['SubjectFrequency'];

	interface CloudWord extends cloud.Word {
		id: number;
		color: string;
	}

	// Nuage des sujets les plus fréquents : la taille et la teinte d'un mot croissent avec le nombre de publications, sur une échelle logarithmique. Chaque mot mène à la fiche du sujet.
	let { subjects }: { subjects: SubjectFrequency[] } = $props();

	const MIN_SIZE = 11;
	const MAX_SIZE = 32;

	let container: HTMLDivElement | undefined = $state();
	let width = $state(0);
	let height = $state(0);
	let placedWords = $state<CloudWord[]>([]);
	let layoutDone = $state(false);

	// Rang d'un sujet entre le moins et le plus fréquent, de 0 à 1.
	function weightFor(count: number, minCount: number, maxCount: number): number {
		if (maxCount === minCount) return 0.5;
		return (
			(Math.log10(count + 1) - Math.log10(minCount + 1)) /
			(Math.log10(maxCount + 1) - Math.log10(minCount + 1))
		);
	}

	// Générateur pseudo-aléatoire à graine fixe (mulberry32) : un même nuage se dispose toujours de la même façon.
	function seededRandom(seed: number): () => number {
		let state = seed;
		return () => {
			state = (state + 0x6d2b79f5) | 0;
			let t = Math.imul(state ^ (state >>> 15), 1 | state);
			t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
			return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
		};
	}

	function buildLayout(list: SubjectFrequency[], w: number, h: number) {
		if (!list.length) {
			placedWords = [];
			layoutDone = true;
			return;
		}
		const counts = list.map((s) => s.count);
		const minCount = Math.min(...counts);
		const maxCount = Math.max(...counts);
		// Teinte : de la plus claire (sujet le moins fréquent) au bleu-vert du site (le plus fréquent).
		const light = cssColor('accent-soft');
		const dark = cssColor('accent');
		const words: CloudWord[] = list.map((s) => {
			const weight = weightFor(s.count, minCount, maxCount);
			return {
				text: s.label,
				size: MIN_SIZE + weight * (MAX_SIZE - MIN_SIZE),
				id: s.id,
				color: mixColors(light, dark, 0.45 + weight * 0.55),
			};
		});

		layoutDone = false;
		cloud<CloudWord>()
			.size([w, h])
			.words(words)
			.padding(3)
			// Texte horizontal uniquement, plus lisible.
			.rotate(() => 0)
			.font('system-ui, sans-serif')
			.fontSize((d) => d.size!)
			.spiral('archimedean')
			.random(seededRandom(1))
			.on('end', (placed: CloudWord[]) => {
				placedWords = placed;
				layoutDone = true;
			})
			.start();
	}

	// Dimensions du nuage, suivies par le conteneur. Tous les mots sont horizontaux : une hauteur compacte suffit.
	function measure() {
		if (!container) return;
		const w = Math.max(300, Math.round(container.getBoundingClientRect().width));
		if (w === width) return;
		width = w;
		height = Math.max(180, Math.round(w * 0.4));
	}

	// Le nuage se recalcule quand les sujets ou la largeur changent.
	$effect(() => {
		if (width > 0) buildLayout(subjects, width, height);
	});

	onMount(() => {
		measure();
		const ro = new ResizeObserver(measure);
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
							style:fill={w.color}
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
		font-size: var(--fs-md);
		margin: 0;
		padding: 12px;
	}
</style>
