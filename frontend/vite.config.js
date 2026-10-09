import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// SPA Gudang (W33). Dev: `npm run dev`, proxy /api|/app|/assets ke site
// produksi (http://127.0.0.1:8088, stack 1oktober2026). Build: `npm run build`
// (base /assets/warehouse_app/gudang/) → bundle di ../warehouse_app/public/gudang
// + www/gudang.html utk route rule hooks.py.
export default defineConfig({
	plugins: [vue()],
	resolve: {
		alias: {
			'@': path.resolve(__dirname, 'src'),
		},
	},
	build: {
		outDir: '../warehouse_app/public/gudang',
		emptyOutDir: true,
		rollupOptions: {
			input: path.resolve(__dirname, 'index.html'),
		},
	},
	server: {
		port: 5173,
		proxy: {
			// desk + login ikut: frappe mengalihkan /app -> /desk dan flow login
			// memakai /login?redirect-to=... — keduanya harus sampai ke site
			'^/(app|desk|login|api|assets|files|printview)': {
				target: process.env.GUDANG_PROXY || 'http://127.0.0.1:8088',
				ws: true,
				changeOrigin: true,
				secure: false,
				cookieDomainRewrite: 'localhost',
			},
		},
	},
})
