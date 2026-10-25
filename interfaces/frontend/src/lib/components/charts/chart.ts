import { Chart, registerables } from 'chart.js';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import { cssColor } from './cssColor';

/**
 * Chart.js enregistré une fois pour toute l'application : composants standard, étiquettes de valeurs, police et couleur de texte lues dans les variables CSS.
 */
Chart.register(...registerables, ChartDataLabels);
Chart.defaults.font.family = getComputedStyle(document.documentElement).getPropertyValue('--font').trim();
Chart.defaults.color = cssColor('text-secondary');

export { Chart };
