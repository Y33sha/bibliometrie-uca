import { describe, expect, it } from 'vitest';
import { specificity } from './specificity';
import { CX, CY, nodeBox, subjectGraphLayout, type Box } from './subjectGraphLayout';

const LABELS = [
	'Social sciences',
	'Environmental Science',
	'Physical Sciences',
	'Agriculture',
	'Agriculture, Dairy & Animal Science',
	'Biologie animale',
	'Genetics',
	'Sciences du Vivant',
	'Biochemistry, Genetics and Molecular Biology',
	'Life Sciences',
	'Agronomy and Crop Science',
	'Health Sciences',
	'Medicine',
	'Animal Science and Zoology',
	'Veterinary Sciences',
	'Agricultural and Biological Sciences',
	'Animal health and immunology',
	'Ruminant Nutrition and Digestive Physiology',
	'Small Animals',
	'Animal Behavior and Welfare Studies'
];

const subject = {
	label_normalized: 'veterinary',
	label: 'Veterinary',
	vocabularies: ['openalex' as const],
	usage_count: 900
};
const neighbors = LABELS.map((label, i) => ({
	label_normalized: label.toLowerCase(),
	label,
	usage_count: 200 + ((i * 397) % 2400),
	cooccurrence_count: 10 + ((i * 53) % 140)
}));
// Deux sujets très liés entre eux, éloignés dans la liste d'origine.
const [linkedA, linkedB] = [neighbors[3].label_normalized, neighbors[10].label_normalized];
const links = [{ label_a: linkedA, label_b: linkedB, cooccurrence_count: 150 }];

function overlaps(a: Box, b: Box): boolean {
	return Math.min(a.x1, b.x1) > Math.max(a.x0, b.x0) && Math.min(a.y1, b.y1) > Math.max(a.y0, b.y0);
}

function expectNoOverlap(layout: ReturnType<ReturnType<typeof subjectGraphLayout>>): void {
	const boxes = layout.nodes.map(nodeBox);
	for (let i = 0; i < boxes.length; i++) {
		expect(overlaps(boxes[i], layout.centerBox)).toBe(false);
		for (let j = i + 1; j < boxes.length; j++) expect(overlaps(boxes[i], boxes[j])).toBe(false);
	}
}

describe('subjectGraphLayout', () => {
	const layoutFor = subjectGraphLayout(subject, neighbors, links);
	const layout = layoutFor(Infinity);

	it('donne des coordonnées finies', () => {
		for (const n of layout.nodes) {
			expect(Number.isFinite(n.x)).toBe(true);
			expect(Number.isFinite(n.y)).toBe(true);
		}
	});

	it('répartit les voisins tout autour du centre', () => {
		const left = layout.nodes.filter((n) => n.x < CX).length;
		const above = layout.nodes.filter((n) => n.y < CY).length;
		expect(left).toBeGreaterThan(5);
		expect(layout.nodes.length - left).toBeGreaterThan(5);
		expect(above).toBeGreaterThan(5);
		expect(layout.nodes.length - above).toBeGreaterThan(5);
	});

	it('ne laisse aucune emprise en recouvrir une autre', () => {
		expectNoOverlap(layout);
	});

	it('coupe un libellé long en deux lignes, à l\'espace le plus proche du milieu', () => {
		const n = layout.nodes.find((m) => m.neighbor.label === 'Biochemistry, Genetics and Molecular Biology')!;
		expect(n.lines).toEqual(['Biochemistry, Genetics', 'and Molecular Biology']);
		expect(layout.nodes.find((m) => m.neighbor.label === 'Genetics')!.lines).toEqual(['Genetics']);
	});

	it('resserre le graphe quand la largeur manque, sans recouvrement', () => {
		const narrow = layoutFor(layout.box.width - 1);
		expect(narrow.box.width).toBeLessThan(layout.box.width);
		expectNoOverlap(narrow);
	});

	it('sépare les libellés de nombreux voisins à 100 % de spécificité', () => {
		const tied = LABELS.slice(0, 12).map((label, i) => ({
			label_normalized: label.toLowerCase(),
			label,
			usage_count: 50 + i * 10,
			cooccurrence_count: 50 + i * 10
		}));
		expectNoOverlap(subjectGraphLayout(subject, tied, [])(Infinity));
	});

	it('donne le placement le plus étroit quand aucun ne tient', () => {
		const narrowest = layoutFor(1);
		expect(narrowest.box.width).toBeLessThanOrEqual(layoutFor(layout.box.width - 1).box.width);
		expectNoOverlap(narrowest);
	});

	it('rapproche du centre les voisins les plus spécifiques', () => {
		const bySpecificity = [...layout.nodes].sort((a, b) => specificity(b.neighbor) - specificity(a.neighbor));
		for (let i = 1; i < bySpecificity.length; i++) {
			expect(bySpecificity[i].distance).toBeGreaterThanOrEqual(bySpecificity[i - 1].distance);
		}
	});

	it('place côte à côte deux sujets très liés', () => {
		const angle = (key: string) => {
			const n = layout.nodes.find((m) => m.neighbor.label_normalized === key)!;
			return Math.atan2(n.y - CY, n.x - CX);
		};
		const diff = Math.abs(angle(linkedA) - angle(linkedB));
		expect(Math.min(diff, 2 * Math.PI - diff)).toBeLessThan((2 * Math.PI) / neighbors.length * 1.6);
	});
});
