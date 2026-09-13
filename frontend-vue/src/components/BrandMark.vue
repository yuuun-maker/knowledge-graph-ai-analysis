<script setup>
defineProps({
  size: { type: Number, default: 72 },
})
</script>

<template>
  <!-- 品牌标识：知识图谱三角节点 + 边，靛蓝→紫品牌渐变 -->
  <svg :width="size" :height="size" viewBox="0 0 48 48" fill="none" aria-hidden="true">
    <defs>
      <linearGradient id="bm-node-a" x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#6f9cf7" />
        <stop offset="1" stop-color="#4f6ef7" />
      </linearGradient>
      <linearGradient id="bm-node-b" x1="12" y1="14" x2="36" y2="40" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#7d8bf8" />
        <stop offset="1" stop-color="#6a5cf6" />
      </linearGradient>
      <linearGradient id="bm-node-c" x1="36" y1="14" x2="12" y2="40" gradientUnits="userSpaceOnUse">
        <stop offset="0" stop-color="#9b8cf8" />
        <stop offset="1" stop-color="#7a63f5" />
      </linearGradient>
    </defs>
    <line x1="24" y1="14" x2="12" y2="37" stroke="#8fa6f5" stroke-width="2.4" stroke-linecap="round" />
    <line x1="24" y1="14" x2="36" y2="37" stroke="#a793f6" stroke-width="2.4" stroke-linecap="round" />
    <line x1="12" y1="37" x2="36" y2="37" stroke="#9aaef6" stroke-width="2.4" stroke-linecap="round" />
    <circle cx="24" cy="14" r="6.4" fill="url(#bm-node-a)" />
    <circle cx="12" cy="37" r="6.4" fill="url(#bm-node-b)" />
    <circle cx="36" cy="37" r="6.4" fill="url(#bm-node-c)" />
    <circle cx="21.6" cy="11.6" r="2" fill="#ffffff" fill-opacity="0.55" />
  </svg>
</template>
