import { ref, watch } from 'vue'
import { loadPref, savePref } from './prefs'

// Tema: 'light' | 'dark' | 'system' — diterapkan via atribut data-theme di
// <html> (selector darkMode preset frappe-ui). Token semantik ikut berbalik
// otomatis; tidak perlu dark: class untuk permukaan ber-token.
const theme = ref(loadPref('theme', 'system'))

function apply() {
	const dark =
		theme.value === 'dark' ||
		(theme.value === 'system' &&
			window.matchMedia('(prefers-color-scheme: dark)').matches)
	document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
}

apply()
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
	if (theme.value === 'system') apply()
})
watch(theme, (v) => {
	savePref('theme', v)
	apply()
})

export function useTheme() {
	return { theme }
}

export function cycleTheme() {
	theme.value = theme.value === 'light' ? 'dark' : theme.value === 'dark' ? 'system' : 'light'
}
