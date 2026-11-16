import { untrack } from 'svelte';

/**
 * Données de l'entité affichée par un volet.
 *
 * À chaque changement d'identifiant, les données de l'entité précédente disparaissent, `onreset` remet à zéro l'état local du volet, puis l'entité se charge. `reload`, après une écriture, recharge l'entité en gardant ses données affichées. Une réponse arrivée après un changement d'identifiant est ignorée.
 */
export function useDrawerEntity<T>(config: {
	id: () => number;
	fetch: (id: number) => Promise<T>;
	onreset?: () => void;
	/** Reçoit les données de chaque chargement de l'entité courante. */
	onload?: (data: T) => void;
}) {
	let data = $state<T | null>(null);
	let failure = $state<unknown>(null);

	async function reload() {
		const current = config.id();
		try {
			const loaded = await config.fetch(current);
			if (current !== config.id()) return;
			data = loaded;
			failure = null;
			config.onload?.(loaded);
		} catch (e) {
			if (current === config.id()) failure = e;
		}
	}

	$effect(() => {
		config.id();
		untrack(() => {
			data = null;
			failure = null;
			config.onreset?.();
			void reload();
		});
	});

	return {
		get data() {
			return data;
		},
		/** Erreur du dernier chargement. */
		get failure() {
			return failure;
		},
		reload,
	};
}
