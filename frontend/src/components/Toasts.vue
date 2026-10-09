<script setup>
import { toasts, dismiss } from '@/lib/toast'
</script>

<template>
	<ul class="toastbox">
		<li v-for="t in toasts" :key="t.id" class="toast" :class="t.type" role="status">
			<span>{{ t.message }}</span>
			<button class="toast-x" aria-label="Tutup" @click="dismiss(t.id)">×</button>
		</li>
	</ul>
</template>
