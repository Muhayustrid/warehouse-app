<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'

const props = defineProps({
	collapsed: { type: Boolean, default: false },
})

// grup = alur kerja; Settings disematkan di dasar sidebar
const sections = [
	{
		title: 'Handover',
		items: [
			{ to: '/', label: 'Requests', icon: 'clipboard' },
			// halaman SPA pengganti shortcut report Desk "Serah Terima Gudang" (W33-r8)
			{ to: '/serah-terima', label: 'Monitoring', icon: 'truck' },
		],
	},
	{
		title: 'Stock',
		items: [{ to: '/inventory', label: 'Inventory Report', icon: 'layers' }],
	},
	// shortcut ERPNext (Material Request/Stock Entry/Stock Balance) dihapus
	// atas keputusan user W33-r9 — akses Desk tetap lewat tombol Desk di topbar
]
const footer = [{ to: '/settings', label: 'Settings', icon: 'settings' }]

// rail ala YouTube: ikon di atas, label mini dua baris di bawah
const itemCls = computed(() =>
	props.collapsed
		? 'flex flex-col items-center gap-1 rounded-lg px-1 py-3 text-[10px] leading-snug text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-9'
		: 'flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-9',
)
const iconCls = computed(() => (props.collapsed ? 'h-5 w-5 shrink-0' : 'h-4 w-4 shrink-0'))
</script>

<template>
	<nav class="flex min-h-full flex-col" :class="collapsed ? 'px-1.5 py-4' : 'px-3 py-4'">
		<div v-for="(section, si) in sections" :key="section.title" :class="si > 0 && (collapsed ? 'mt-2' : 'mt-6')">
			<div v-if="collapsed && si > 0" class="mx-auto mb-2 h-px w-8 bg-outline-gray-2" />
			<p v-if="!collapsed" class="px-2.5 pb-1.5 text-xs font-medium text-ink-gray-5">
				{{ section.title }}
			</p>
			<div :class="collapsed ? 'space-y-1' : 'space-y-0.5'">
				<RouterLink
					v-for="item in section.items"
					:key="item.to"
					:to="item.to"
					:class="itemCls"
					:title="collapsed ? `${section.title} ${item.label}` : undefined"
					exact-active-class="bg-surface-gray-3 !text-ink-gray-9 font-medium"
				>
					<FeatherIcon :name="item.icon" :class="iconCls" />
					<span v-if="collapsed" class="line-clamp-2 w-full break-words text-center">
						{{ item.label }}
					</span>
					<template v-else>{{ item.label }}</template>
				</RouterLink>
			</div>
		</div>
		<div class="mt-auto pt-6" :class="collapsed ? 'space-y-1' : 'space-y-0.5'">
			<RouterLink
				v-for="item in footer"
				:key="item.to"
				:to="item.to"
				:class="itemCls"
				:title="collapsed ? item.label : undefined"
				exact-active-class="bg-surface-gray-3 !text-ink-gray-9 font-medium"
			>
				<FeatherIcon :name="item.icon" :class="iconCls" />
				<span v-if="collapsed" class="line-clamp-2 w-full break-words text-center">{{ item.label }}</span>
				<template v-else>{{ item.label }}</template>
			</RouterLink>
		</div>
	</nav>
</template>
