import { definePreset } from '@primevue/themes'
import Aura from '@primevue/themes/aura'

// Preset PrimeVue disetel mengikuti abu frappe-ui (hex dari
// frappe-ui/tailwind colors.json). PENTING: skala surface di KEDUA skema
// harus absolut (0 terang … 950 gelap) — skema dark tidak menimpa skala,
// melainkan merujuk ujung yang sesuai (teks dark = surface.0, latar kartu =
// surface.900/950). Karena itu token teks/primary dark dioverride eksplisit
// ke nilai frappe agar teks tidak murni putih dan aksi tetap charcoal.
// Dark mode global memakai selector [data-theme] yang sama dengan preset
// frappe-ui (lihat theme.js) — satu atribut membalik keduanya.

const SURFACE_ABSOLUTE = {
	0: '#FFFFFF',
	50: '#F8F8F8',
	100: '#F3F3F3',
	200: '#EDEDED',
	300: '#E2E2E2',
	400: '#C7C7C7',
	500: '#999999',
	600: '#7C7C7C',
	700: '#525252',
	800: '#383838',
	900: '#171717',
	950: '#0F0F0F',
}

const PRIMARY_RAMP = {
	50: '#F8F8F8',
	100: '#F3F3F3',
	200: '#EDEDED',
	300: '#E2E2E2',
	400: '#C7C7C7',
	500: '#999999',
	600: '#7C7C7C',
	700: '#525252',
	800: '#383838',
	900: '#171717',
	950: '#0F0F0F',
}

export const gudangPreset = definePreset(Aura, {
	semantic: {
		// aksi primer = charcoal frappe (Button solid frappe-ui juga gelap)
		primary: PRIMARY_RAMP,
		colorScheme: {
			light: {
				surface: SURFACE_ABSOLUTE,
			},
			dark: {
				primary: {
					color: '#AFAFAF',
					contrastColor: '#171717',
					hoverColor: '#C7C7C7',
					activeColor: '#D4D4D4',
				},
				surface: SURFACE_ABSOLUTE,
				text: {
					color: '#D4D4D4',
					hoverColor: '#F8F8F8',
					mutedColor: '#808080',
					hoverMutedColor: '#AFAFAF',
				},
				highlight: {
					background: 'rgba(212, 212, 212, 0.12)',
					focusBackground: 'rgba(212, 212, 212, 0.18)',
					color: '#F8F8F8',
					focusColor: '#F8F8F8',
				},
			},
		},
	},
})
