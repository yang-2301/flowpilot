<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api } from "../api";
import type { Run } from "../types";

const route = useRoute();
const runId = route.params.id as string;
const run = ref<Run | null>(null);
const error = ref("");
const busy = ref(false);

const wfName = ref("");

onMounted(async () => {
  try {
    run.value = await api.get<Run>(`/api/runs/${runId}`);
    const wfs = await api.get<any[]>("/api/workflows");
    wfName.value = wfs.find((w) => w.id === run.value?.workflow_id)?.name ?? "";
  } catch (e: any) {
    error.value = e.message;
  }
});

const totalMs = computed(() => {
  if (!run.value?.steps) return 0;
  return run.value.steps.reduce((acc, s) => acc + s.duration_ms, 0);
});

async function replay() {
  busy.value = true;
  try {
    const r = await api.post<{ run_id: string }>(`/api/runs/${runId}/replay`);
    location.href = `/runs/${r.run_id}`;
  } catch (e: any) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <p v-if="error" class="error-text">{{ error }}</p>

  <div v-else-if="run">
    <div class="head">
      <h1>Run <span class="mono">{{ run.id }}</span></h1>
      <button class="primary" :disabled="busy" @click="replay">
        {{ busy ? "Replaying…" : "Replay" }}
      </button>
    </div>

    <p class="muted">
      {{ wfName || run.workflow_id }}
      · started {{ run.started_at.slice(0, 19).replace('T', ' ') }} UTC
      · total {{ totalMs }} ms
      <span v-if="run.replay_of"> · replay of <code class="inline">{{ run.replay_of }}</code></span>
    </p>

    <div class="status-line">
      <span class="badge" :class="'status-' + run.status">{{ run.status }}</span>
      <span v-if="run.error" class="error-text">{{ run.error }}</span>
    </div>

    <div class="card">
      <h2>Trigger payload</h2>
      <pre class="mono payload">{{ JSON.stringify(run.trigger_payload, null, 2) }}</pre>
    </div>

    <h2 style="margin: 16px 0 8px">Step timeline</h2>
    <div class="timeline">
      <div v-for="s in run.steps" :key="s.idx" class="step card"
           :class="'step-' + s.status">
        <div class="step-head">
          <span class="idx mono">#{{ s.idx + 1 }}</span>
          <strong>{{ s.name }}</strong>
          <span class="muted mono">{{ s.type }}</span>
          <span class="badge" :class="'status-' + s.status">{{ s.status }}</span>
          <div class="spacer" />
          <span class="muted">
            {{ s.duration_ms }} ms
            <template v-if="s.attempts > 1">
              · <strong class="retried">{{ s.attempts }} attempts</strong>
            </template>
          </span>
        </div>
        <p v-if="s.error" class="error-text mono">{{ s.error }}</p>
        <pre v-if="s.output" class="mono payload">{{ JSON.stringify(s.output, null, 2).slice(0, 600) }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
.status-line { display: flex; align-items: center; gap: 10px; margin: 10px 0 16px; }
.payload { background: #f8fafc; border-radius: 8px; padding: 10px; margin: 0; max-height: 200px; overflow: auto; }
.timeline { display: flex; flex-direction: column; gap: 10px; }
.step-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.idx { color: var(--muted); }
.spacer { flex: 1; }
.retried { color: #d97706; }
.step-failed { border-left: 3px solid var(--danger); }
.step-skipped { border-left: 3px solid #cbd5e1; }
.step-ok { border-left: 3px solid var(--ok); }
</style>
