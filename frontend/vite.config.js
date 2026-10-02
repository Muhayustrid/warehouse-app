import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'
import { defineConfig } from 'vite'

// SPA Gudang (W33). Pola meniru pos_next/POS (satu-satunya frappe-ui app
// yang terbukti jalan di stack ini):
// - dev: `npm run dev`, proxy /api|/app|/assets ke site produksi
//   (http://127.0.0.1:8088, stack 1oktober2026) — site tidak perlu diubah.
// - build: `npm run build` (base /assets/warehouse_app/gudang/) → bundle di
//   ../warehouse_app/public/gudang + www/gudang.html utk route rule hooks.py.
export default defineConfig({
	plugins: [
		frappeui({
			// wajib true: barrel frappe-ui menarik TextEditor yang mengimpor
			// virtual module ~icons/lucide/* (resolver unplugin-icons)
			lucideIcons: true,
			buildConfig: {
				indexHtmlPath: '../warehouse_app/www/gudang.html',
				outDir: '../warehouse_app/public/gudang',
				emptyOutDir: true,
			},
		}),
		vue(),
	],
	resolve: {
		alias: {
			'@': path.resolve(__dirname, 'src'),
			// deep-import source frappe-ui tanpa barrel (Gameplan-style): barrel
			// menarik seluruh komponen (TextEditor/echarts) sehingga tak bisa
			// di-pre-bundle esbuild — import per-komponen menjaga graf tetap
			// kecil dan hanya feather-icons (UMD) yang butuh pre-bundle.
			'@frappe-ui': path.resolve(__dirname, 'node_modules/frappe-ui/src'),
		},
	},
	// frappe-ui (TS + .vue) tidak boleh di-pre-bundle esbuild; feather-icons
	// (UMD/CJS) HARUS di-pre-bundle supaya interop default-export-nya benar.
	// Specifier @frappe-ui/* (alias deep-import) ikut di-exclude — tanpa ini
	// optimizer membuat chunk @frappe-ui_* yang merusak handler komponen.
	optimizeDeps: {
		exclude: [
			'frappe-ui',
			'@frappe-ui/components/Button',
			'@frappe-ui/components/Checkbox',
			'@frappe-ui/components/TabButtons',
			'@frappe-ui/components/Popover',
			'@frappe-ui/components/Autocomplete',
			'@frappe-ui/components/FormControl',
			'@frappe-ui/components/TextInput',
			'@frappe-ui/components/Dialog',
			'@frappe-ui/components/FeatherIcon.vue',
			'@frappe-ui/components/Toast/Toast.vue',
			'@frappe-ui/components/DatePicker',
			'@frappe-ui/resources',
			'@frappe-ui/utils/frappeRequest.js',
			'@frappe-ui/utils/dayjs',
		],
		include: ['feather-icons'],
	},
	server: {
		port: 5173,
		proxy: {
			// desk + login ikut: frappe mengalihkan /app -> /desk dan flow login
			// memakai /login?redirect-to=... — keduanya harus sampai ke site
			'^/(app|desk|login|api|assets|files|printview)': {
				target: 'http://127.0.0.1:8088',
				ws: true,
				changeOrigin: true,
				secure: false,
				cookieDomainRewrite: 'localhost',
			},
		},
	},
})
