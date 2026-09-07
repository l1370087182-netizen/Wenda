<script setup>
import { toasts } from '../composables/toast'
import Icon from './Icon.vue'

const ICONS = { success: 'check-circle', error: 'alert-circle', warn: 'alert-circle', info: 'zap' }
</script>

<template>
  <div class="toast-stack">
    <transition-group name="fade">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="`toast-${t.type}`">
        <span class="t-bar"></span>
        <Icon :name="ICONS[t.type] || 'zap'" :size="15" />
        <span>{{ t.message }}</span>
      </div>
    </transition-group>
  </div>
</template>
