import { describe, it, expect } from 'vitest';
import { highlight } from './highlight';

describe('highlight', () => {
	it('repère le terme sans tenir compte des accents ni de la casse', () => {
		expect(highlight('Écologie microbienne', 'ecologie')).toEqual([
			{ text: 'Écologie', match: true },
			{ text: ' microbienne', match: false },
		]);
	});

	it('repère chaque occurrence', () => {
		expect(highlight('Micro et micro', 'MICRO').filter((s) => s.match).map((s) => s.text)).toEqual(['Micro', 'micro']);
	});

	it('renvoie le texte entier pour un terme vide ou absent', () => {
		expect(highlight('Physique', ' ')).toEqual([{ text: 'Physique', match: false }]);
		expect(highlight('Physique', 'chimie')).toEqual([{ text: 'Physique', match: false }]);
	});
});
