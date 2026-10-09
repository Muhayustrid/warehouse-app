<script setup>
import { ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import Toasts from '@/components/Toasts.vue'
import SideNav from '@/components/SideNav.vue'
import { sessionUser } from '@/lib/session'
import { initials } from '@/lib/format'
import {
	Boxes,
	ChevronDown,
	LayoutGrid,
	ListChecks,
	Package,
	Settings,
	Warehouse,
} from 'lucide-vue-next'

const user = sessionUser()
const route = useRoute()
// drawer ala production_workspace: burger membukanya di SEMUA lebar layar
// (rail lipat versi lama dibuang — tak ada yang memakainya di template)
const navOpen = ref(false)
const userMenu = ref(false)

// tutup drawer & menu profil saat pindah halaman
watch(
	() => route.path,
	() => {
		navOpen.value = false
		userMenu.value = false
	},
)
</script>

<template>
	<div class="app" :class="{ 'nav-open': navOpen }">
		<div class="backdrop" aria-hidden="true" @click="navOpen = false"></div>

		<header class="topbar">
			<button class="navburger" aria-label="Buka/tutup menu" @click="navOpen = !navOpen">
				<span class="bars"><span></span><span></span><span></span></span>
			</button>
			<div class="brand">
				<span class="brandmark"><Warehouse :size="18" :stroke-width="1.9" /></span>
				<div class="brandtext">
					<span class="brandname">GUDANG<span class="brandtint">APP</span></span>
					<span class="brandsub">Warehouse workspace</span>
				</div>
			</div>
			<div class="topuser">
				<button
					type="button"
					class="userbtn"
					:aria-expanded="userMenu"
					aria-haspopup="menu"
					aria-label="Menu pengguna"
					@click="userMenu = !userMenu"
					@keydown.esc="userMenu = false"
				>
					<span class="avatar">{{ initials(user) }}</span>
					<span class="uinfo">
						<span class="uname">{{ user }}</span>
						<span class="urole">ERPNext</span>
					</span>
					<ChevronDown :size="14" :stroke-width="2" class="uchev" :class="{ open: userMenu }" />
				</button>
				<template v-if="userMenu">
					<div class="usermenu-overlay" aria-hidden="true" @click="userMenu = false"></div>
					<transition name="pop" appear>
						<div class="usermenu" role="menu">
							<a role="menuitem" class="usermenu-item" href="/app">
								<LayoutGrid :size="16" :stroke-width="1.9" />
								Buka ERPNext Desk
							</a>
						</div>
					</transition>
				</template>
			</div>
		</header>

		<aside class="sidenav" aria-label="Navigasi utama">
			<div class="sideinner">
				<div class="sidedrop">
					<button class="navburger" aria-label="Tutup menu" @click="navOpen = false">
						<span class="bars"><span></span><span></span><span></span></span>
					</button>
					<div class="brand">
						<span class="brandmark"><Warehouse :size="18" :stroke-width="1.9" /></span>
						<div class="brandtext">
							<span class="brandname">GUDANG<span class="brandtint">APP</span></span>
							<span class="brandsub">Warehouse workspace</span>
						</div>
					</div>
				</div>
				<SideNav />
			</div>
		</aside>

		<nav class="bottomnav" aria-label="Navigasi utama">
			<RouterLink to="/" class="bnav-item" :class="{ on: route.path === '/' }">
				<span class="bnav-ic"><ListChecks :size="20" :stroke-width="1.9" /></span>
				<span class="bnav-label">Requests</span>
			</RouterLink>
			<RouterLink to="/serah-terima" class="bnav-item" :class="{ on: route.path === '/serah-terima' }">
				<span class="bnav-ic"><Package :size="20" :stroke-width="1.9" /></span>
				<span class="bnav-label">Monitoring</span>
			</RouterLink>
			<RouterLink to="/inventory" class="bnav-item" :class="{ on: route.path === '/inventory' }">
				<span class="bnav-ic"><Boxes :size="20" :stroke-width="1.9" /></span>
				<span class="bnav-label">Inventory</span>
			</RouterLink>
			<RouterLink to="/settings" class="bnav-item" :class="{ on: route.path === '/settings' }">
				<span class="bnav-ic"><Settings :size="20" :stroke-width="1.9" /></span>
				<span class="bnav-label">Lainnya</span>
			</RouterLink>
		</nav>

		<div class="maincol">
			<div class="content" :class="{ wide: route.meta.wide }">
				<div :key="route.path" class="view-anim">
					<RouterView />
				</div>
			</div>
		</div>

		<Toasts />
	</div>
</template>
