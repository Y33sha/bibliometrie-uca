<script module lang="ts">
	import Check from '@lucide/svelte/icons/check';
	import PanelRight from '@lucide/svelte/icons/panel-right';
	import Pencil from '@lucide/svelte/icons/pencil';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import Trash from '@lucide/svelte/icons/trash';
	import X from '@lucide/svelte/icons/x';

	const ICONS = { edit: Pencil, delete: Trash, panel: PanelRight, reject: X, confirm: Check, reset: RotateCcw };
</script>

<script lang="ts">
	// Bouton d'action réduit à son icône : crayon pour modifier, corbeille pour supprimer, panneau latéral pour ouvrir un volet, croix pour rejeter, coche pour valider, flèche circulaire pour réinitialiser. Le libellé sert d'infobulle et de nom accessible.
	let {
		icon,
		label,
		onclick,
		disabled = false,
		pressed,
		small = false
	}: {
		icon: keyof typeof ICONS;
		label: string;
		onclick: () => void;
		disabled?: boolean;
		/** Fait du bouton une bascule : enfoncé, il garde la couleur de son action. */
		pressed?: boolean;
		/** Version compacte, logée dans une étiquette. */
		small?: boolean;
	} = $props();

	const Icon = $derived(ICONS[icon]);
</script>

<button
	type="button"
	class="icon-btn"
	class:icon-btn-danger={icon === 'delete' || icon === 'reject'}
	class:icon-btn-success={icon === 'confirm'}
	class:icon-btn-sm={small}
	title={label}
	aria-label={label}
	aria-pressed={pressed}
	{disabled}
	{onclick}
>
	<Icon size={15} />
</button>
