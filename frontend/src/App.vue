<script setup>
import { ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import Toasts from '@/components/Toasts.vue'
import SideNav from '@/components/SideNav.vue'
import FeatherIcon from '@frappe-ui/components/FeatherIcon.vue'
import { useTheme, cycleTheme } from '@/lib/theme'
import { sessionUser } from '@/lib/session'
import { initials } from '@/lib/format'
import { loadPref, savePref } from '@/lib/prefs'

const { theme } = useTheme()
const user = sessionUser()
const route = useRoute()
const mobileNav = ref(false)

// sidebar desktop bisa dilipat ala YouTube; keadaan diingat lintas kunjungan
const collapsed = ref(loadPref('sidebar_collapsed', false))

function toggleNav() {
	if (window.matchMedia('(min-width: 768px)').matches) {
		collapsed.value = !collapsed.value
		savePref('sidebar_collapsed', collapsed.value)
	} else {
		mobileNav.value = !mobileNav.value
	}
}

const themeIcon = { light: 'sun', dark: 'moon', system: 'monitor' }

// tutup drawer mobile saat pindah halaman
watch(
	() => route.path,
	() => {
		mobileNav.value = false
	},
)
</script>

<template>
	<!-- topbar: identitas + utilitas (navigasi pindah ke sidebar ala Desk) -->
	<header class="sticky top-0 z-30 border-b border-outline-gray-1 bg-surface-modal">
		<div class="flex h-14 items-center px-4 sm:px-6">
			<div class="flex items-center gap-1.5">
				<button
					class="flex h-8 w-8 items-center justify-center rounded-md text-ink-gray-6 hover:bg-surface-gray-3 hover:text-ink-gray-9"
					aria-label="Menu"
					@click="toggleNav"
				>
					<FeatherIcon name="menu" class="h-4 w-4" />
				</button>
				<div class="mx-1 h-5 w-px bg-[var(--outline-gray-2)]" aria-hidden="true" />
				<div class="flex items-center gap-2">
					<!-- logo app yang sama dgn Desk (hooks add_to_apps_screen) -->
					<img :src="'/assets/warehouse_app/logo.svg'" alt="" class="h-8 w-8 shrink-0" />
					<span class="text-base font-semibold tracking-tight text-ink-gray-9">Gudang</span>
				</div>
			</div>
			<div class="ml-auto flex items-center gap-1.5">
				<button
					class="flex h-8 w-8 items-center justify-center rounded-md text-ink-gray-6 hover:bg-surface-gray-3 hover:text-ink-gray-9"
					:title="`Theme: ${theme}`"
					@click="cycleTheme()"
				>
					<FeatherIcon :name="themeIcon[theme] || 'sun'" class="h-4 w-4" />
				</button>
				<a
					href="/app"
					class="hidden h-8 items-center gap-1.5 rounded-md px-2.5 text-sm font-medium text-ink-gray-6 hover:bg-surface-gray-3 hover:text-ink-gray-9 sm:flex"
					title="Open ERPNext Desk"
				>
					Desk
					<FeatherIcon name="external-link" class="h-3.5 w-3.5" />
				</a>
				<div
					class="ml-1 flex h-8 w-8 items-center justify-center rounded-full bg-surface-gray-4 text-xs font-semibold text-ink-gray-7"
					:title="user"
				>
					{{ initials(user) }}
				</div>
			</div>
		</div>
	</header>

	<div class="flex flex-1">
		<!-- sidebar desktop: penuh <-> rail ikon ala YouTube -->
		<aside
			class="hidden shrink-0 border-r border-outline-gray-1 bg-surface-modal md:block"
			:class="collapsed ? 'w-[4.5rem]' : 'w-60'"
		>
			<div class="sticky top-14 max-h-[calc(100vh-3.5rem)] overflow-y-auto">
				<SideNav :collapsed="collapsed" />
			</div>
		</aside>

		<!-- drawer mobile -->
		<template v-if="mobileNav">
			<div
				class="fixed inset-0 z-40 bg-ink-gray-9/30 md:hidden"
				@click="mobileNav = false"
			/>
			<aside
				class="fixed bottom-0 left-0 top-14 z-40 w-60 overflow-y-auto border-r border-outline-gray-1 bg-surface-modal md:hidden"
			>
				<SideNav />
			</aside>
		</template>

		<main
			class="mx-auto w-full min-w-0 flex-1 px-4 pb-16 pt-6 sm:px-6"
			:class="route.meta.wide ? 'max-w-none' : 'max-w-6xl'"
		>
			<RouterView />
		</main>
	</div>
	<Toasts />
</template>
