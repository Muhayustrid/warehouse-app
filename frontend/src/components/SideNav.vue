<script setup>
import { useRoute } from 'vue-router'
import { ClipboardList, Layers, Settings } from 'lucide-vue-next'

// seksi Handover + Stock; Settings di dasar. counts via props (opsional).
defineProps({
	counts: { type: Object, default: () => ({}) },
})

const route = useRoute()

const sections = [
	{
		title: 'Handover',
		items: [{ to: '/', label: 'Requests', icon: ClipboardList, count: 'requests' }],
	},
	{
		title: 'Stock',
		items: [{ to: '/inventory', label: 'Inventory Report', icon: Layers }],
	},
	// shortcut ERPNext (Material Request/Stock Entry/Stock Balance) dihapus
	// atas keputusan user W33-r9 — akses Desk tetap lewat menu profil topbar
]
const footer = [{ to: '/settings', label: 'Settings', icon: Settings }]
</script>

<template>
	<nav class="flex flex-col min-h-full">
		<template v-for="(section, si) in sections" :key="section.title">
			<div class="navsection" :style="si > 0 ? 'margin-top:18px' : ''">
				{{ section.title }}
			</div>
			<RouterLink
				v-for="item in section.items"
				:key="item.to"
				:to="item.to"
				class="navitem"
				:class="{ on: route.path === item.to }"
				:aria-current="route.path === item.to ? 'page' : undefined"
			>
				<component :is="item.icon" :size="18" :stroke-width="1.9" class="nicon" />
				<span class="nlabel">{{ item.label }}</span>
				<span v-if="item.count && counts[item.count]" class="navbadge">{{ counts[item.count] }}</span>
			</RouterLink>
		</template>

		<div style="margin-top:auto; padding-top:18px">
			<RouterLink
				v-for="item in footer"
				:key="item.to"
				:to="item.to"
				class="navitem"
				:class="{ on: route.path === item.to }"
				:aria-current="route.path === item.to ? 'page' : undefined"
			>
				<component :is="item.icon" :size="18" :stroke-width="1.9" class="nicon" />
				<span class="nlabel">{{ item.label }}</span>
			</RouterLink>
		</div>
	</nav>
</template>
