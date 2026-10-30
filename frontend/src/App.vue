<script setup>
import { computed, onMounted, ref } from "vue";
import { applyPlan, createPlan, fetchItems, listRoots, undoOp } from "./api.js";
import PreviewTable from "./components/PreviewTable.vue";
import ProgressBar from "./components/ProgressBar.vue";
import DirectoryPicker from "./components/DirectoryPicker.vue";

const roots = ref([]);
const root = ref("");
const picking = ref(false);
const page = ref(1);
const pageSize = 200;
const decision = ref("");
const reason = ref("");

const planId = ref(null);
const counts = ref({});
const total = ref(0);
const items = ref([]);
const selected = ref(new Set());
const phase = ref("idle"); // idle | scanning | ready | applying | done
const error = ref("");
const message = ref("");
const lastOp = ref(null);
const elapsed = ref(0);

const canApply = computed(() => phase.value === "ready" && selected.value.size > 0);
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

function humanTime(seconds) {
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
}

onMounted(async () => {
  try {
    const data = await listRoots();
    roots.value = data.roots || [];
    if (roots.value.length) root.value = roots.value[0];
  } catch (e) {
    error.value = String(e.message || e);
  }
});

async function loadPage(targetPage = 1) {
  if (!planId.value) return;
  const body = await fetchItems(planId.value, {
    page: targetPage,
    size: pageSize,
    decision: decision.value,
    reason: reason.value,
  });
  items.value = body.items;
  total.value = body.total;
  page.value = targetPage;
}

async function scan() {
  error.value = "";
  message.value = "";
  if (!root.value) {
    error.value = "请先填写素材目录";
    return;
  }
  phase.value = "scanning";
  const started = performance.now();
  try {
    const body = await createPlan({
      root: root.value,
      copy: false,
      move_unlocated: false,
      allow_estimate: false,
    });
    planId.value = body.plan_id;
    counts.value = body.counts || {};
    const tick = setInterval(() => (elapsed.value = (performance.now() - started) / 1000), 250);
    await loadPage(1);
    clearInterval(tick);
    phase.value = "ready";
    message.value = `扫描完成：${body.total} 个文件，用时 ${humanTime(elapsed.value)}`;
  } catch (e) {
    phase.value = "idle";
    error.value = String(e.message || e);
  }
}

function toggle(path) {
  const next = new Set(selected.value);
  next.has(path) ? next.delete(path) : next.add(path);
  selected.value = next;
}

function selectAllVisible() {
  const next = new Set(selected.value);
  items.value.forEach((row) => {
    if (row.decision === "rename" || row.decision === "move") next.add(row.item.path);
  });
  selected.value = next;
}

function clearSelection() {
  selected.value = new Set();
}

async function runApply(dryRun) {
  if (!planId.value) return;
  error.value = "";
  phase.value = "applying";
  try {
    const paths = selected.value.size ? Array.from(selected.value) : null;
    const body = await applyPlan(planId.value, { paths, dry_run: dryRun });
    lastOp.value = body.op_id;
    phase.value = "done";
    message.value = dryRun
      ? `演练完成：${body.steps} 步，未改动任何文件`
      : `执行完成（op ${body.op_id}）：${body.steps} 步`;
    if (!dryRun) await loadPage(page.value);
  } catch (e) {
    phase.value = "ready";
    error.value = String(e.message || e);
  }
}

async function undoLast() {
  if (!lastOp.value) return;
  try {
    const body = await undoOp(lastOp.value);
    message.value = body.ok ? `已撤销：${body.reverted} 步` : `撤销中止：${body.conflicts.join(", ")}`;
    await loadPage(page.value);
  } catch (e) {
    error.value = String(e.message || e);
  }
}

function exportPlan() {
  if (!planId.value) return;
  fetchItems(planId.value, { page: 1, size: 2000 })
    .then((body) => {
      const blob = new Blob([JSON.stringify(body, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `qorg-plan-${planId.value}.json`;
      a.click();
      URL.revokeObjectURL(url);
    })
    .catch((e) => (error.value = String(e.message || e)));
}
</script>

<template>
  <main>
    <header>
      <h1>qorg 素材整理</h1>
      <p class="sub">按 GPS 解析出的省/市归档，文件名补 <code>_省_市_YYMMDD</code>，做错可一键撤销。</p>
    </header>

    <section class="card">
      <label for="root">素材目录</label>
      <div class="row">
        <input id="root" v-model="root" list="roots" placeholder="/home/you/Pictures/2024旅行" />
        <datalist id="roots">
          <option v-for="r in roots" :key="r" :value="r" />
        </datalist>
        <button class="ghost" :disabled="phase === 'scanning'" @click="picking = true">
          浏览…
        </button>
        <button :disabled="phase === 'scanning'" @click="scan">
          {{ phase === "scanning" ? "扫描中…" : "扫描" }}
        </button>
      </div>
      <p v-if="roots.length" class="roots-hint">
        可访问根目录：{{ roots.join(" · ") }}
      </p>
      <ProgressBar v-if="phase === 'scanning'" :elapsed="elapsed" />
      <p v-if="message" class="ok">{{ message }}</p>
      <p v-if="error" class="err">{{ error }}</p>
    </section>

    <section v-if="planId" class="card">
      <div class="row filters">
        <select v-model="decision" @change="loadPage(1)">
          <option value="">全部决策</option>
          <option value="rename">rename</option>
          <option value="move">move</option>
          <option value="keep">keep</option>
          <option value="skip">skip</option>
        </select>
        <select v-model="reason" @change="loadPage(1)">
          <option value="">全部原因</option>
          <option value="no_gps">no_gps</option>
          <option value="abroad">abroad</option>
          <option value="needs_city_level_data">needs_city_level_data</option>
          <option value="unreadable">unreadable</option>
          <option value="symlink">symlink</option>
        </select>
        <span class="counts">
          共 {{ total }} 条 · rename {{ counts.rename || 0 }} · keep {{ counts.keep || 0 }} ·
          skip {{ counts.skip || 0 }}
        </span>
        <button class="ghost" @click="selectAllVisible">全选本页可处理</button>
        <button class="ghost" @click="clearSelection">清空选择</button>
      </div>

      <PreviewTable
        :items="items"
        :selected="selected"
        @toggle="toggle"
      />

      <div class="row pager">
        <button class="ghost" :disabled="page <= 1" @click="loadPage(page - 1)">上一页</button>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="ghost" :disabled="page >= totalPages" @click="loadPage(page + 1)">下一页</button>
      </div>

      <div class="row actions">
        <button :disabled="!planId" @click="runApply(true)">演练（不改文件）</button>
        <button class="primary" :disabled="!canApply" @click="runApply(false)">
          执行所选（{{ selected.size }}）
        </button>
        <button class="ghost" :disabled="!lastOp" @click="undoLast">撤销本次</button>
        <button class="ghost" @click="exportPlan">导出结果 JSON</button>
      </div>
    </section>

    <DirectoryPicker
      v-if="picking"
      :model-value="root"
      :roots="roots"
      @update:model-value="root = $event"
      @close="picking = false"
    />

    <footer>
      <p>执行前一定先看一遍目标路径；没有 GPS 的文件默认原地不动。</p>
    </footer>
  </main>
</template>

<style>
:root {
  color-scheme: light dark;
  --bg: #0f1115;
  --card: #171a21;
  --ink: #e8eaf0;
  --muted: #98a2b3;
  --accent: #5b8cff;
  --warn: #ffb454;
  --ok: #3ecf8e;
  --err: #ff6b6b;
}
* { box-sizing: border-box; }
body { margin: 0; font: 14px/1.5 "PingFang SC", "Noto Sans SC", system-ui, sans-serif; background: var(--bg); color: var(--ink); }
main { max-width: 1180px; margin: 0 auto; padding: 28px 20px 60px; }
h1 { font-size: 22px; margin: 0 0 6px; }
.sub { color: var(--muted); margin: 0 0 20px; }
code { background: #22262f; padding: 1px 5px; border-radius: 4px; }
.card { background: var(--card); border: 1px solid #232733; border-radius: 10px; padding: 16px; margin-bottom: 16px; }
.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
input, select { background: #10131a; color: var(--ink); border: 1px solid #2a3040; border-radius: 8px; padding: 8px 10px; min-width: 200px; }
button { background: #232838; color: var(--ink); border: 1px solid #2f3547; border-radius: 8px; padding: 8px 14px; cursor: pointer; }
button:disabled { opacity: .45; cursor: not-allowed; }
button.primary { background: var(--accent); border-color: var(--accent); color: #08101f; font-weight: 600; }
button.ghost { background: transparent; }
.filters .counts { color: var(--muted); margin-left: auto; }
.actions { justify-content: flex-end; }
.roots-hint { color: var(--muted); font-size: 12px; margin: 8px 0 0; }
.ok { color: var(--ok); margin: 10px 0 0; }
.err { color: var(--err); margin: 10px 0 0; }
footer { color: var(--muted); font-size: 12px; }
</style>
