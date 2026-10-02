import frappeUIPreset from 'frappe-ui/tailwind'

export default {
	presets: [frappeUIPreset],
	// preset frappe-ui memakai selector [data-theme="dark"] — semua token
	// semantik (bg-surface-*, text-ink-*, border-outline-*) ikut berbalik
	// otomatis; dark:... di template hanya untuk palet mentah (pills status).
	content: [
		'./index.html',
		'./src/**/*.{vue,js,ts,jsx,tsx}',
		'./node_modules/frappe-ui/src/components/**/*.{vue,js,ts,jsx,tsx}',
	],
}
