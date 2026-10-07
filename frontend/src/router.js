import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
	history: createWebHistory('/gudang'),
	routes: [
		{
			path: '/',
			name: 'board',
			component: () => import('@/pages/BoardPage.vue'),
		},
		{
			path: '/serah-terima',
			name: 'serahTerima',
			component: () => import('@/pages/SerahTerimaPage.vue'),
		},
		{
			path: '/inventory',
			name: 'inventory',
			component: () => import('@/pages/InventoryPage.vue'),
			// tabel ledger lebar: main tanpa max-w-6xl (App.vue)
			meta: { wide: true },
		},
		{
			path: '/settings',
			name: 'settings',
			component: () => import('@/pages/SettingsPage.vue'),
		},
		{ path: '/:pathMatch(.*)*', redirect: '/' },
	],
})
