import svelte from 'eslint-plugin-svelte';
import svelteParser from 'svelte-eslint-parser';
import tsParser from '@typescript-eslint/parser';

/* Analyse ciblée : deux règles, `svelte/no-at-html-tags` et l'interdiction d'afficher un titre
 * de publication sans son rendu (`TITRE_AFFICHE_BRUT`).
 *
 * `{@html}` insère du HTML sans échappement — c'est le seul endroit du frontend où une valeur
 * reçue d'une source externe peut devenir du code exécutable. Les valeurs qui y passent sont
 * assainies par liste blanche (`sanitizeTitle`, `sanitizeAbstract`), et deux composants sont
 * seuls à les insérer. La règle tient cette concentration : un `{@html}` échoue à l'analyse,
 * et l'admettre demande d'inscrire son fichier ci-dessous.
 *
 * Les dérogations sont portées par la configuration plutôt que par un commentaire au point
 * d'appel : le parseur Svelte n'expose pas les commentaires du gabarit à l'analyseur, si bien
 * qu'une directive posée dans le balisage resterait lettre morte. Les réunir ici a d'ailleurs
 * un mérite propre — la liste des points d'insertion de HTML se lit d'un coup d'œil.
 *
 * Le reste du jeu de règles n'est pas activé : `svelte-check` tient déjà les types, et une
 * adoption complète est un chantier distinct.
 */

/* Fichiers où `{@html}` est admis, avec l'assainissement qui le justifie. Y ajouter un fichier
 * est un geste délibéré : la valeur insérée doit passer par `#lib/utils.js`. */
const RENDU_HTML_ASSAINI = [
	// `sanitizeTitle` — titres de publication (formatage et MathML déposés par les sources).
	'src/lib/components/PublicationTitle.svelte',
	// `sanitizeAbstract` — résumés (mêmes règles, paragraphes en plus).
	'src/lib/components/PublicationAbstract.svelte'
];

/* Champs de titre de publication. Un titre porte du formatage déposé par les sources (MathML,
 * LaTeX, balises) : dans un gabarit, il passe par `PublicationTitle` (prop `titre`), ou par
 * `titleText` là où seul du texte est admis (titre d'onglet, info-bulle). `columnLabels.title`
 * est le libellé d'une colonne. */
const CHAMP_TITRE = '/^(title|monograph_title|publication_title)$/';

const TITRE_AFFICHE_BRUT = {
	selector:
		`SvelteMustacheTag MemberExpression[property.name=${CHAMP_TITRE}][object.name!='columnLabels']` +
		`:not(SvelteAttribute[key.name='titre'] *)` +
		`:not(CallExpression[callee.name='titleText'] *)`,
	message:
		'Titre affiché sans rendu : passer par <PublicationTitle titre={…} />, ou par titleText(…) là où seul du texte est admis.'
};

/* Fichiers où `title` désigne autre chose qu'un titre de publication : revues, aide, boîtes de dialogue. */
const TITRES_HORS_PUBLICATIONS = [
	'src/lib/components/DialogHost.svelte',
	'src/lib/components/SerialsListView.svelte',
	'src/routes/journals/**',
	'src/routes/admin/feedback/+page.svelte'
];

export default [
	{
		ignores: ['build/', '.svelte-kit/', 'node_modules/', 'src/lib/api/schema.ts']
	},
	{
		files: ['**/*.svelte'],
		languageOptions: {
			parser: svelteParser,
			// Les blocs `<script lang="ts">` sont lus par le parseur TypeScript, que le parseur
			// Svelte délègue pour le contenu du script.
			parserOptions: { parser: tsParser }
		},
		plugins: { svelte },
		rules: {
			'svelte/no-at-html-tags': 'error',
			'no-restricted-syntax': ['error', TITRE_AFFICHE_BRUT]
		}
	},
	{
		files: TITRES_HORS_PUBLICATIONS,
		rules: {
			'no-restricted-syntax': 'off'
		}
	},
	{
		files: RENDU_HTML_ASSAINI,
		rules: {
			'svelte/no-at-html-tags': 'off'
		}
	}
];
