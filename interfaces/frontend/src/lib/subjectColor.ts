// Palette tournante des sujets, commune au nuage de sujets et au graphe d'un sujet. Couleur non sémantique, stable pour un même sujet.
const PALETTE = ['#075985', '#0369a1', '#7c3aed', '#9333ea', '#be123c', '#b45309'];

export function subjectColor(id: number): string {
	return PALETTE[id % PALETTE.length];
}
