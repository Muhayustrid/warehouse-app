import { createApp } from 'vue'
import PrimeVue from 'primevue/config'
import App from './App.vue'
import router from './router'
import { initSession } from './lib/session'
import { gudangPreset } from './lib/primevue'
import 'primeicons/primeicons.css'
import './gudang.css'
import './primevue.css'

async function start() {
	await initSession()
	const app = createApp(App)
	// error render/hook komponen terlihat — bukan di-swallow diam-diam
	app.config.errorHandler = (err, _inst, info) => {
		window.__vueError = String((err && (err.stack || err.message)) || err) + ' [' + info + ']'
		console.error('[gudang-spa]', err, info)
	}
	// PrimeVue (W33-r8): komponen data (DataTable/Select/Dialog) Inventory.
	// Terang-saja — darkModeSelector dimatikan.
	app.use(PrimeVue, {
		theme: {
			preset: gudangPreset,
			options: { darkModeSelector: 'none' },
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
