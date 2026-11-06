<script lang="ts">
	import { resolve } from '$app/paths';
	import GlobalSearch from '#lib/components/search/GlobalSearch.svelte';
	import { siteTitle } from '#lib/institution.svelte.js';

	// Page d'accueil : recherche transverse, puis questions types. Chaque question ouvre la vue Statistiques de la liste des publications avec ses réglages.
	interface Question {
		label: string;
		detail: string;
		settings: Record<string, string>;
	}

	const QUESTIONS: Question[] = [
		{
			label: 'Quels laboratoires publient le plus en accès ouvert ?',
			detail: "Part des publications en accès ouvert, par laboratoire",
			settings: { indicator: 'oa_access', group_by: 'lab', mode: 'part', chart_sort: 'ouvert' },
		},
		{
			label: 'Combien coûtent les APC ?',
			detail: 'Montant des frais de publication, par année et par voie d’accès',
			settings: { indicator: 'apc_amount' },
		},
		{
			label: 'Dans quelles revues publie-t-on le plus ?',
			detail: 'Nombre de publications par revue',
			settings: { group_by: 'serial' },
		},
		{
			label: "Comment évolue l'impact des publications ?",
			detail: 'Part des articles, chapitres et conference papers parmi les plus cités, par année',
			settings: { doc_type: 'article,book_chapter,conference_paper', indicator: 'citation_class', mode: 'part' },
		},
	];

	function questionUrl(q: Question): string {
		return `${resolve('publications')}?${new URLSearchParams({ view: 'stats', ...q.settings })}`;
	}
</script>

<svelte:head><title>{siteTitle()}</title></svelte:head>

<section class="home">
	<h1 class="home-title">Explorer la production scientifique</h1>
	<GlobalSearch />

	<h2 class="questions-title">Questions</h2>
	<ul class="questions">
		{#each QUESTIONS as q (q.label)}
			<li>
				<a class="question" href={questionUrl(q)}>
					<span class="question-label">{q.label}</span>
					<span class="question-detail">{q.detail}</span>
				</a>
			</li>
		{/each}
	</ul>
</section>

<style>
	.home {
		max-width: 760px;
		margin: 56px auto 0;
	}
	.home-title {
		margin: 0 0 20px;
		font-family: var(--font-brand);
		font-size: var(--fs-xl);
		font-weight: 600;
		text-align: center;
		text-wrap: balance;
	}
	.questions-title {
		margin: 48px 0 6px;
		font-size: var(--fs-sm);
		font-weight: 600;
		color: var(--muted);
	}
	.questions {
		margin: 0;
		padding: 0;
		list-style: none;
	}
	.questions li + li {
		border-top: 1px solid var(--border-subtle);
	}
	/* Question : libellé en couleur d'accent, réglages du graphique en dessous ; flèche à droite, qui avance au survol. */
	.question {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 10px 32px 10px 0;
		text-decoration: none;
	}
	.question::after {
		content: '→';
		position: absolute;
		right: 8px;
		top: 50%;
		transform: translateY(-50%);
		color: var(--muted);
		transition: transform 0.15s;
	}
	.question:hover::after {
		color: var(--accent);
		transform: translate(4px, -50%);
	}
	.question-label {
		font-size: var(--fs-base);
		font-weight: 600;
		color: var(--accent);
	}
	.question:hover .question-label {
		color: color-mix(in srgb, var(--accent), black 20%);
	}
	.question-detail {
		font-size: var(--fs-sm);
		color: var(--muted);
	}
</style>
