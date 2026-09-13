<script setup>
defineProps({
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
})
</script>

<template>
  <div class="page-header">
    <span class="page-header-bar"></span>
    <div class="page-header-text">
      <h2 class="page-title">{{ title }}</h2>
      <p v-if="desc" class="page-desc">{{ desc }}</p>
    </div>
    <div class="page-header-extra">
      <slot name="extra"></slot>
    </div>
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}
.page-header-bar {
  width: 5px;
  height: 26px;
  border-radius: 4px;
  background: var(--gradient-brand);
  box-shadow: 0 3px 8px -2px rgba(79,110,247,.55);
  flex-shrink: 0;
}
.page-header-text {
  flex: 1;
  min-width: 0;
}
.page-title {
  margin: 0;
  font-size: var(--font-size-title);
  font-weight: 700;
  line-height: 1.3;
  color: var(--color-text-primary);
  letter-spacing: .3px;
}
.page-desc {
  margin: 3px 0 0;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.page-header-extra {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
