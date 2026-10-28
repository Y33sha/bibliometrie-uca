// Teinte de l'interface appliquée avant le premier affichage : la dernière teinte servie par l'API, gardée par `applyBrandHue` (institution.svelte.ts). Fichier externe, la CSP refusant les scripts inline hors SvelteKit.
try {
	const hue = localStorage.getItem('brand-hue');
	if (hue !== null) document.documentElement.style.setProperty('--brand-hue', hue);
} catch {
	// Stockage inaccessible : la teinte par défaut de shared.css s'applique jusqu'au chargement de l'établissement.
}
