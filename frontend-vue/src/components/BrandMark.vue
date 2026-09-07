<script setup>
defineProps({
  size: { type: Number, default: 72 },
})
</script>

<template>
  <!-- 品牌标识：知识图谱三角节点 + 边，主色蓝（#409eff / #66b1ff / #a0cfff） -->
  <svg :width="size" :height="size" viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <line x1="24" y1="14" x2="12" y2="37" stroke="#409eff" stroke-width="2.4" stroke-linecap="round" />
    <line x1="24" y1="14" x2="36" y2="37" stroke="#409eff" stroke-width="2.4" stroke-linecap="round" />
    <line x1="12" y1="37" x2="36" y2="37" stroke="#409eff" stroke-width="2.4" stroke-linecap="round" />
    <circle cx="24" cy="14" r="6.2" fill="#409eff" />
    <circle cx="12" cy="37" r="6.2" fill="#66b1ff" />
    <circle cx="36" cy="37" r="6.2" fill="#a0cfff" />
  </svg>
</template>
