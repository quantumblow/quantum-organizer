<script setup>
defineProps({
  items: { type: Array, default: () => [] },
  selected: { type: Object, default: () => new Set() },
});
const emit = defineEmits(["toggle"]);

function decisionClass(decision) {
  return {
    rename: "tag rename",
    move: "tag move",
    keep: "tag keep",
    skip: "tag skip",
  }[decision] || "tag";
}

function reasonText(item) {
  return item.reason || (item.geo_boundary ? "boundary" : "");
}
</script>

<template>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th class="pick"></th>
          <th>原文件</th>
          <th>拍摄时间</th>
          <th>省 / 第二级</th>
          <th>目标路径</th>
          <th>状态</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in items" :key="row.item.path" :class="{ muted: row.decision !== 'rename' && row.decision !== 'move' }">
          <td class="pick">
            <input
              type="checkbox"
              :checked="selected.has(row.item.path)"
              :disabled="row.decision !== 'rename' && row.decision !== 'move'"
              @change="emit('toggle', row.item.path)"
            />
          </td>
          <td class="name" :title="row.item.path">{{ row.item.path.split('/').pop() }}</td>
          <td>{{ row.item.shoot_time || "—" }}<span class="src">{{ row.item.time_source || "" }}</span></td>
          <td>{{ row.item.province || "—" }} / {{ row.item.city || "—" }}</td>
          <td class="target">{{ row.target_path || "（不移动）" }}</td>
          <td>
            <span :class="decisionClass(row.decision)">{{ row.decision }}</span>
            <span v-if="reasonText(row.item)" class="reason">{{ reasonText(row.item) }}</span>
            <span v-if="row.conflict" class="reason">{{ row.conflict }}</span>
          </td>
        </tr>
        <tr v-if="!items.length">
          <td colspan="6" class="empty">没有条目</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.table-wrap { max-height: 60vh; overflow: auto; margin-top: 12px; border: 1px solid #232733; border-radius: 8px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #1e222c; vertical-align: top; }
th { position: sticky; top: 0; background: #1b1f29; font-weight: 600; z-index: 1; }
tr.muted { color: #7d8698; }
.pick { width: 34px; }
.name { max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.target { max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #b9c2d4; }
.src, .reason { color: #7d8698; font-size: 11px; margin-left: 6px; }
.tag { padding: 1px 6px; border-radius: 4px; font-size: 12px; background: #2a3040; }
.tag.rename { background: #24406b; color: #cfe0ff; }
.tag.move { background: #3b3320; color: #ffe1a8; }
.tag.keep { background: #232733; color: #9aa4b8; }
.tag.skip { background: #3a2430; color: #ffc7d8; }
.empty { text-align: center; color: var(--muted); padding: 24px; }
</style>
