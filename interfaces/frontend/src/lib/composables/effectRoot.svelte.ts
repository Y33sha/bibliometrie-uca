/**
 * Exécute `fn` dans un scope d'effet racine (`$effect.root`), hors de tout
 * composant. Permet d'instancier en test un composable qui utilise `$effect`
 * (sinon Svelte lève `effect_orphan`). Retourne la valeur produite par `fn`
 * + un `cleanup` à appeler en fin de test pour disposer le scope et ses effets.
 *
 * Vit dans un fichier `.svelte.ts` car `$effect.root` est une rune (non
 * disponible dans un `.test.ts` ordinaire).
 */
export function runInEffectRoot<T>(fn: () => T): { value: T; cleanup: () => void } {
	let value!: T;
	const cleanup = $effect.root(() => {
		value = fn();
	});
	return { value, cleanup };
}
