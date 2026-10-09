import { definePreset } from '@primevue/themes'
import Aura from '@primevue/themes/aura'

// Preset PrimeVue terang-saja, disetel ke token gudang.css (biru --brand).
// Tanpa dark scheme — darkModeSelector dimatikan di main.js.
export const gudangPreset = definePreset(Aura, {
	semantic: {
		primary: {
			50: '#eff5f9',
			100: '#e3eef5',
			200: '#c5dde9',
			300: '#9ec4d8',
			400: '#66a3bf',
			500: '#3368a0',
			600: '#2a5585',
			700: '#24476e',
			800: '#1d3a5a',
			900: '#162c45',
			950: '#0e1c2d',
		},
	},
})
