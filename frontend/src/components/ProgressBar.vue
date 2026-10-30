<script setup>
defineProps({ elapsed: { type: Number, default: 0 } });
</script>

<template>
  <div class="bar">
    <div class="fill"></div>
    <span>扫描中 · {{ Math.round(elapsed) }} 秒</span>
  </div>
</template>

<style scoped>
.bar { position: relative; height: 6px; border-radius: 3px; background: #232733; margin-top: 12px; overflow: hidden; }
.fill { position: absolute; inset: 0; width: 40%; background: var(--accent); animation: slide 1.2s ease-in-out infinite; }
.bar span { display: block; margin-top: 8px; font-size: 12px; color: var(--muted); }
@keyframes slide {
  0% { transform: translateX(-60%); }
  100% { transform: translateX(260%); }
}
</style>
