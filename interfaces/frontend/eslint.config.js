import svelte from 'eslint-plugin-svelte';
import svelteParser from 'svelte-eslint-parser';
import tsParser from '@typescript-eslint/parser';

/* Analyse ciblée : une seule règle, `svelte/no-at-html-tags`.
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
 * est un geste délibéré : la valeur insérée doit passer par `$lib/utils`. */
const RENDU_HTML_ASSAINI = [
	// `sanitizeTitle` — titres de publication (formatage et MathML déposés par les sources).
	'src/lib/components/PublicationTitle.svelte',
	// `sanitizeAbstract` — résumés (mêmes règles, paragraphes en plus).
	'src/lib/components/PublicationAbstract.svelte'
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
			'svelte/no-at-html-tags': 'error'
		}
	},
	{
		files: RENDU_HTML_ASSAINI,
		rules: {
			'svelte/no-at-html-tags': 'off'
		}
	}
];
