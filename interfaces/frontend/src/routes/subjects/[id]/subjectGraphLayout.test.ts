import { describe, expect, it } from 'vitest';
import { CX, CY, INNER_RING, nodeBox, subjectGraphLayout, type Box } from './subjectGraphLayout';

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

const subject = { id: 1, label: 'Veterinary', language: null, usage_count: 900 };
const neighbors = LABELS.map((label, i) => ({
	id: 100 + i,
	label,
	usage_count: 200 + ((i * 397) % 2400),
	cooccurrence_count: 10 + ((i * 53) % 140)
}));
// Deux sujets très liés entre eux, éloignés dans la liste d'origine.
const links = [{ subject_a_id: 103, subject_b_id: 110, cooccurrence_count: 150 }];

function overlaps(a: Box, b: Box): boolean {
	return Math.min(a.x1, b.x1) > Math.max(a.x0, b.x0) && Math.min(a.y1, b.y1) > Math.max(a.y0, b.y0);
}

describe('subjectGraphLayout', () => {
	const layout = subjectGraphLayout(subject, neighbors, links);

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
		const boxes = layout.nodes.map(nodeBox);
		for (let i = 0; i < boxes.length; i++) {
			expect(overlaps(boxes[i], layout.centerBox)).toBe(false);
			for (let j = i + 1; j < boxes.length; j++) expect(overlaps(boxes[i], boxes[j])).toBe(false);
		}
	});

	it('laisse le voisin le plus spécifique sur l\'anneau intérieur', () => {
		const closest = Math.min(...layout.nodes.map((n) => n.distance));
		expect(closest).toBe(INNER_RING);
	});

	it('place côte à côte deux sujets très liés', () => {
		const angle = (id: number) => {
			const n = layout.nodes.find((m) => m.neighbor.id === id)!;
			return Math.atan2(n.y - CY, n.x - CX);
		};
		const diff = Math.abs(angle(103) - angle(110));
		expect(Math.min(diff, 2 * Math.PI - diff)).toBeLessThan((2 * Math.PI) / neighbors.length * 1.6);
	});
});
