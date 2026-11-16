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
			path: '/fulfillment',
			name: 'fulfillment',
			component: () => import('@/pages/FulfillmentPage.vue'),
			meta: { wide: true },
		},
		{
			path: '/fulfillment/:id',
			name: 'fulfillment-workspace',
			alias: ['/fulfillment/run/:id'],
			component: () => import('@/pages/FulfillmentWorkspacePage.vue'),
			meta: { wide: true },
		},
		{
			path: '/packing-slips',
			name: 'packing-slips',
			component: () => import('@/pages/PackingSlipPage.vue'),
			meta: { wide: true },
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
