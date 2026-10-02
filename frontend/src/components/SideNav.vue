<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'

const props = defineProps({
	collapsed: { type: Boolean, default: false },
})

const sections = [
	{
		title: 'Gudang',
		items: [
			{ to: '/', label: 'Handover Requests', icon: 'clipboard-list' },
			// halaman SPA pengganti shortcut report Desk (W33-r8)
			{ to: '/serah-terima', label: 'Serah Terima Gudang', icon: 'truck' },
			{ to: '/settings', label: 'Settings', icon: 'settings' },
		],
	},
	// shortcut ERPNext (Material Request/Stock Entry/Stock Balance) dihapus
	// atas keputusan user W33-r9 — akses Desk tetap lewat tombol Desk di topbar
]

// rail ala YouTube: ikon di atas, label mini dua baris di bawah
const itemCls = computed(() =>
	props.collapsed
		? 'flex flex-col items-center gap-1 rounded-lg px-1 py-3 text-[10px] leading-snug text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-9'
		: 'flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-ink-gray-6 hover:bg-surface-gray-2 hover:text-ink-gray-9',
)
const iconCls = computed(() => (props.collapsed ? 'h-5 w-5 shrink-0' : 'h-4 w-4 shrink-0'))
</script>

<template>
	<nav :class="collapsed ? 'px-1.5 py-4' : 'px-3 py-4'">
		<template v-for="(section, si) in sections" :key="section.title">
			<div v-if="collapsed && si > 0" class="mx-auto my-2 h-px w-8 bg-outline-gray-2" />
			<p
				v-if="!collapsed"
				class="px-2.5 pb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-gray-4"
				:class="si > 0 ? 'pt-5' : ''"
			>
				{{ section.title }}
			</p>
			<div :class="collapsed ? 'space-y-1' : 'space-y-0.5'">
				<RouterLink
					v-for="item in section.items"
					:key="item.to"
					:to="item.to"
					:class="itemCls"
					:title="collapsed ? item.label : undefined"
					exact-active-class="bg-surface-gray-3 !text-ink-gray-9 font-medium"
				>
					<FeatherIcon :name="item.icon" :class="iconCls" />
					<span v-if="collapsed" class="line-clamp-2 w-full break-words text-center">
						{{ item.label }}
					</span>
					<template v-else>{{ item.label }}</template>
				</RouterLink>
			</div>
		</template>
	</nav>
</template>
