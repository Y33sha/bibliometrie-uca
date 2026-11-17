import { describe, expect, it } from 'vitest';
import { yearAxis } from './yearAxis';

describe('yearAxis', () => {
	it('gradue chaque année, et non les demi-années des bornes', () => {
		const axis = yearAxis([2021, 2022, 2024]);
		const scale = { ticks: [{ value: 2020.5 }, { value: 2021.5 }] };
		axis.afterBuildTicks(scale);
		expect(scale.ticks).toEqual([{ value: 2021 }, { value: 2022 }, { value: 2024 }]);
		expect([axis.min, axis.max]).toEqual([2020.5, 2024.5]);
	});
});
