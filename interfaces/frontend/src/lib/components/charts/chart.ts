import { Chart, registerables } from 'chart.js';
import ChartDataLabels from 'chartjs-plugin-datalabels';
import { cssColor, cssVar, fontSize } from './cssVar';

/**
 * Chart.js enregistré une fois pour toute l'application : composants standard, étiquettes de valeurs, police, taille et couleur de texte lues dans les variables CSS.
 */
Chart.register(...registerables, ChartDataLabels);
Chart.defaults.font.family = cssVar('font');
Chart.defaults.font.size = fontSize('sm');
Chart.defaults.color = cssColor('text-secondary');

export { Chart };
