<script setup>
import { state, _finish } from '../composables/confirm'
</script>

<template>
  <transition name="fade">
    <div v-if="state.open" class="modal-backdrop" @click.self="_finish(false)">
      <transition name="pop" appear>
        <div class="modal">
          <h3>{{ state.title }}</h3>
          <p>{{ state.message }}</p>
          <div class="modal-actions">
            <button class="btn btn-ghost btn-sm" @click="_finish(false)">{{ state.cancelText }}</button>
            <button class="btn btn-sm" :class="state.danger ? 'btn-danger' : 'btn-primary'" @click="_finish(true)">
              {{ state.confirmText }}
            </button>
          </div>
        </div>
      </transition>
    </div>
  </transition>
</template>
