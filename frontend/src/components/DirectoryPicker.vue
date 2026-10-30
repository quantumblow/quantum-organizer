<script setup>
import { computed, onMounted, ref } from "vue";
import { browse } from "../api.js";

const props = defineProps({
  modelValue: { type: String, default: "" },
  roots: { type: Array, default: () => [] },
});
const emit = defineEmits(["update:modelValue", "close"]);

const current = ref("");
const dirs = ref([]);
const parent = ref(null);
const error = ref("");
const loading = ref(false);

const crumbs = computed(() => {
  const parts = [];
  let acc = "";
  for (const seg of current.value.split("/").filter(Boolean)) {
    acc += `/${seg}`;
    parts.push({ name: seg, path: acc });
  }
  return parts;
});

async function open(path) {
  loading.value = true;
  error.value = "";
  try {
    const body = await browse(path);
    current.value = body.path;
    dirs.value = body.dirs || [];
    parent.value = body.parent;
    if (body.error === "permission_denied") {
      error.value = "这个目录没有读取权限，换一个吧";
    }
  } catch (e) {
    error.value = String(e.message || e);
  } finally {
    loading.value = false;
  }
}

function choose() {
  emit("update:modelValue", current.value);
  emit("close");
}

onMounted(() => {
  const start = props.modelValue && props.modelValue.startsWith("/")
    ? props.modelValue
    : props.roots[0];
  open(start);
});
</script>

<template>
  <div class="backdrop" @click.self="emit('close')">
    <div class="picker">
      <header>
        <strong>选择素材目录</strong>
        <button class="ghost small" @click="emit('close')">关闭</button>
      </header>

      <div class="roots">
        <button
          v-for="r in roots"
          :key="r"
          class="chip"
          :class="{ active: r === current }"
          @click="open(r)"
        >
          {{ r }}
        </button>
      </div>

      <nav class="crumbs">
        <button class="ghost small" :disabled="!parent" @click="open(parent)">↑ 上级</button>
        <button
          v-for="c in crumbs"
          :key="c.path"
          class="ghost small crumb"
          @click="open(c.path)"
        >
          {{ c.name }}
        </button>
      </nav>

      <p class="path">{{ current }}</p>
      <p v-if="error" class="err">{{ error }}</p>
      <p v-if="loading" class="muted">加载中…</p>

      <ul class="dirs">
        <li v-if="!dirs.length && !loading && !error" class="muted">这个目录下没有子文件夹</li>
        <li v-for="d in dirs" :key="d.path">
          <button class="dir" @click="open(d.path)">📁 {{ d.name }}</button>
        </li>
      </ul>

      <footer>
        <button class="primary" :disabled="!current" @click="choose">用这个目录</button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; background: rgba(6, 8, 12, .72);
  display: flex; align-items: center; justify-content: center; padding: 20px; z-index: 30;
}
.picker {
  background: var(--card); border: 1px solid #232733; border-radius: 12px;
  width: min(720px, 100%); max-height: 80vh; display: flex; flex-direction: column; padding: 16px;
}
header { display: flex; justify-content: space-between; align-items: center; }
.roots { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
.chip { background: #1b1f29; border: 1px solid #2a3040; border-radius: 999px; padding: 4px 10px; font-size: 12px; }
.chip.active { border-color: var(--accent); color: var(--accent); }
.crumbs { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.crumb::before { content: "/"; margin-right: 4px; color: var(--muted); }
.path { font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); margin: 10px 0; word-break: break-all; }
.dirs { list-style: none; margin: 0; padding: 0; overflow: auto; flex: 1; }
.dir { width: 100%; text-align: left; background: transparent; border: 1px solid transparent; padding: 6px 8px; border-radius: 6px; }
.dir:hover { background: #1d2230; border-color: #2a3040; }
.small { padding: 4px 10px; font-size: 12px; }
.muted { color: var(--muted); font-size: 13px; }
.err { color: var(--err); font-size: 13px; }
footer { display: flex; justify-content: flex-end; margin-top: 12px; }
</style>
