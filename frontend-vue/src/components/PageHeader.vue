<script setup>
defineProps({
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
})
</script>

<template>
  <div class="page-header">
    <h2 class="page-title">{{ title }}</h2>
    <p v-if="desc" class="page-desc">{{ desc }}</p>
  </div>
</template>

<style scoped>
.page-header {
  margin-bottom: var(--space-4);
}
.page-title {
  margin: 0 0 4px;
  font-size: var(--font-size-title);
  font-weight: var(--font-weight-bold);
  line-height: 1.3;
  color: var(--color-text-primary);
}
.page-desc {
  margin: 0;
  font-size: 13px;
  color: var(--color-text-secondary);
}
</style>
