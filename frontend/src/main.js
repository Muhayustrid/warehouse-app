import { createApp } from 'vue'
import { resourcesPlugin } from '@frappe-ui/resources'
import PrimeVue from 'primevue/config'
import App from './App.vue'
import router from './router'
import { initSession } from './lib/session'
import { gudangPreset } from './lib/primevue'
import 'primeicons/primeicons.css'
import './primevue.css'
import './index.css'

async function start() {
	await initSession()
	const app = createApp(App)
	// error render/hook komponen terlihat — bukan di-swallow diam-diam
	app.config.errorHandler = (err, _inst, info) => {
		window.__vueError = String((err && (err.stack || err.message)) || err) + ' [' + info + ']'
		console.error('[gudang-spa]', err, info)
	}
	app.use(resourcesPlugin)
	// PrimeVue (W33-r8): komponen data (DataTable/Select) halaman Serah
	// Terima Gudang. Dark selector = atribut data-theme yang sama dgn preset
	// frappe-ui, jadi satu toggle membalik kedua library.
	app.use(PrimeVue, {
		theme: {
			preset: gudangPreset,
			options: { darkModeSelector: '[data-theme="dark"]' },
		},
		ripple: false,
	})
	app.use(router)
	app.mount('#app')
}

// kegagalan boot harus terlihat — SPA kosong tanpa pesan adalah jebakan
start().catch((e) => {
	const pre = document.createElement('pre')
	pre.style.cssText =
		'position:fixed;inset:auto 16px 16px 16px;z-index:99999;background:#1a1a1a;color:#ffb4b4;padding:12px;border-radius:8px;font-size:12px;white-space:pre-wrap'
	pre.textContent = 'BOOT ERROR: ' + ((e && (e.stack || e.message)) || String(e))
	document.body?.append(pre)
})
