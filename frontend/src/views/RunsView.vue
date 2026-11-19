<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api } from "../api";
import type { Run } from "../types";

const router = useRouter();
const runs = ref<Run[]>([]);
const loading = ref(true);
const error = ref("");
const statusFilter = ref("");

async function load() {
  loading.value = true;
  try {
    const qs = statusFilter.value ? `?status=${statusFilter.value}` : "";
    runs.value = await api.get<Run[]>(`/api/runs${qs}&page_size=50`);
  } catch (e: any) {
    error.value = e.message;
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>

<template>
  <h1>Runs</h1>

  <div class="card">
    <div class="filters">
      <select v-model="statusFilter" @change="load">
        <option value="">All statuses</option>
        <option value="success">Success</option>
        <option value="failed">Failed</option>
        <option value="dead">Dead (retries exhausted)</option>
        <option value="skipped">Skipped (condition false)</option>
      </select>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>
    <p v-if="loading" class="muted">Loading…</p>

    <table v-if="!loading && runs.length">
      <thead>
        <tr><th>Run</th><th>Workflow</th><th>Status</th><th>Started</th><th>Finished</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in runs" :key="r.id" class="row-link" @click="router.push(`/runs/${r.id}`)">
          <td class="mono">
            {{ r.id }}
            <span v-if="r.replay_of" class="muted">replay of {{ r.replay_of.slice(0, 6) }}</span>
          </td>
          <td class="mono muted">{{ r.workflow_id }}</td>
          <td><span class="badge" :class="'status-' + r.status">{{ r.status }}</span></td>
          <td class="muted">{{ r.started_at.slice(11, 19) }} UTC</td>
          <td class="muted">{{ r.finished_at ? r.finished_at.slice(11, 19) : "—" }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="!loading" class="muted">No runs match.</p>
  </div>
</template>

<style scoped>
.filters { margin-bottom: 10px; max-width: 260px; }
</style>
