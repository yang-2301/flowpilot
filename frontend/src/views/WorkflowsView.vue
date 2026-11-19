<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { api, setToken, getToken } from "../api";
import type { Workflow, Run } from "../types";

const router = useRouter();
const workflows = ref<Workflow[]>([]);
const runsByWf = ref<Record<string, Run[]>>({});
const error = ref("");
const token = ref(getToken());
const tokenSaved = ref(false);

const editing = ref(false);
const editJson = ref("");
const editName = ref("");
const editId = ref<string | null>(null);
const editError = ref("");
const saving = ref(false);

const copied = ref("");

async function load() {
  try {
    workflows.value = await api.get<Workflow[]>("/api/workflows");
    for (const wf of workflows.value) {
      runsByWf.value[wf.id] = await api.get<Run[]>(
        `/api/runs?workflow_id=${wf.id}&page_size=5`);
    }
  } catch (e: any) {
    error.value = e.message;
  }
}
onMounted(load);

function saveToken() {
  setToken(token.value.trim());
  tokenSaved.value = true;
  setTimeout(() => (tokenSaved.value = false), 1500);
  load();
}

function hookUrl(wf: Workflow): string {
  const secret = wf.trigger_config?.secret ?? "";
  return `${location.origin}/hooks/${wf.id}/${secret}`;
}

async function copy(text: string, what: string) {
  await navigator.clipboard.writeText(text);
  copied.value = what;
  setTimeout(() => (copied.value = ""), 1500);
}

async function fire(wf: Workflow) {
  try {
    const payload = wf.name.includes("flaky")
      ? { bucket: Math.random().toString(36).slice(2, 6) }
      : { email: "jane@acme.io", company: "Acme", source: "console",
          company_size: 500 };
    const r = await api.post<{ run_id: string }>(
      `/hooks/${wf.id}/${wf.trigger_config?.secret}`, payload);
    router.push(`/runs/${r.run_id}`);
  } catch (e: any) {
    error.value = e.message;
  }
}

function startEdit(wf: Workflow) {
  editing.value = true;
  editId.value = wf.id;
  editName.value = wf.name;
  editJson.value = JSON.stringify(wf.steps, null, 2);
  editError.value = "";
}

function newWorkflow() {
  editing.value = true;
  editId.value = null;
  editName.value = "New workflow";
  editJson.value = JSON.stringify([
    { type: "transform", name: "prep", config: { template: { ok: true } }, max_attempts: 1 },
  ], null, 2);
}

async function save() {
  saving.value = true;
  editError.value = "";
  try {
    const steps = JSON.parse(editJson.value);
    const existing = editId.value
      ? workflows.value.find((w) => w.id === editId.value)!
      : null;
    const body = {
      name: editName.value,
      description: existing?.description ?? "Created from console",
      trigger_type: existing?.trigger_type ?? "webhook",
      trigger_config: existing?.trigger_config ?? {},
      steps,
      enabled: existing?.enabled ?? true,
    };
    if (editId.value) {
      await api.put(`/api/workflows/${editId.value}`, body);
    } else {
      await api.post("/api/workflows", body);
    }
    editing.value = false;
    await load();
  } catch (e: any) {
    editError.value = e.message;
  } finally {
    saving.value = false;
  }
}

async function toggle(wf: Workflow) {
  try {
    await api.put(`/api/workflows/${wf.id}`, { ...wf, enabled: !wf.enabled });
    await load();
  } catch (e: any) {
    error.value = e.message;
  }
}

async function remove(wf: Workflow) {
  if (!confirm(`Delete workflow "${wf.name}" and its runs?`)) return;
  await api.del(`/api/workflows/${wf.id}`);
  await load();
}
</script>

<template>
  <div class="head">
    <h1>Workflows</h1>
    <button class="primary" @click="newWorkflow">New workflow</button>
  </div>

  <p v-if="error" class="error-text">{{ error }}</p>

  <div class="card token-row">
    <span class="muted">Admin token:</span>
    <input v-model="token" class="token-input mono" />
    <button @click="saveToken">Save</button>
    <span v-if="tokenSaved" class="muted">saved ✓</span>
  </div>

  <div v-if="editing" class="card editor">
    <h2>{{ editId ? "Edit" : "New" }} workflow</h2>
    <input v-model="editName" placeholder="Workflow name" style="margin-bottom: 8px" />
    <textarea v-model="editJson" class="code" rows="14" spellcheck="false" />
    <p v-if="editError" class="error-text">{{ editError }}</p>
    <div class="row">
      <button class="primary" :disabled="saving" @click="save">
        {{ saving ? "Saving…" : "Save (server validates)" }}
      </button>
      <button @click="editing = false">Cancel</button>
    </div>
  </div>

  <div v-for="wf in workflows" :key="wf.id" class="card wf">
    <div class="wf-head">
      <strong class="wf-name">{{ wf.name }}</strong>
      <span class="badge" :class="'type-' + wf.trigger_type">{{ wf.trigger_type }}</span>
      <span class="badge" :class="wf.enabled ? 'status-ok' : 'status-skipped'">
        {{ wf.enabled ? "enabled" : "disabled" }}
      </span>
      <div class="spacer" />
      <button v-if="wf.trigger_type === 'webhook'" class="primary" @click="fire(wf)">
        Fire test event
      </button>
      <button @click="startEdit(wf)">Edit</button>
      <button @click="toggle(wf)">{{ wf.enabled ? "Disable" : "Enable" }}</button>
      <button class="danger" @click="remove(wf)">Delete</button>
    </div>

    <p class="muted">{{ wf.description }}</p>

    <div class="steps">
      <template v-for="(s, i) in wf.steps" :key="i">
        <span class="step-chip" :title="'max_attempts: ' + s.max_attempts">
          <span class="mono step-type">{{ s.type }}</span> {{ s.name }}
          <span v-if="s.max_attempts > 1" class="retry">×{{ s.max_attempts }}</span>
        </span>
        <span v-if="i < wf.steps.length - 1" class="arrow">→</span>
      </template>
    </div>

    <div v-if="wf.trigger_type === 'webhook'" class="hook-line">
      <code class="inline mono">POST {{ hookUrl(wf) }}</code>
      <button class="mini" @click="copy(hookUrl(wf), wf.id)">
        {{ copied === wf.id ? "copied ✓" : "copy" }}
      </button>
    </div>

    <table v-if="runsByWf[wf.id]?.length">
      <thead><tr><th>Recent runs</th><th>Status</th><th>Started</th></tr></thead>
      <tbody>
        <tr v-for="r in runsByWf[wf.id]" :key="r.id" class="row-link"
            @click="router.push(`/runs/${r.id}`)">
          <td class="mono">{{ r.id }}<span v-if="r.replay_of" class="muted"> · replay</span></td>
          <td><span class="badge" :class="'status-' + r.status">{{ r.status }}</span></td>
          <td class="muted">{{ r.started_at.slice(0, 19).replace('T', ' ') }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else class="muted">No runs yet.</p>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
.token-row { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; padding: 10px 16px; }
.token-input { width: 220px; }
.editor { margin-bottom: 16px; }
.editor .row { display: flex; gap: 8px; margin-top: 8px; }
.wf { margin-bottom: 16px; }
.wf-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.wf-name { font-size: 15px; }
.spacer { flex: 1; }
.steps { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin: 10px 0; }
.step-chip {
  background: #f8fafc; border: 1px solid var(--border);
  border-radius: 8px; padding: 4px 10px; font-size: 12px;
}
.step-type { color: var(--accent); margin-right: 4px; }
.retry { color: var(--muted); font-size: 11px; }
.arrow { color: var(--muted); }
.hook-line { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.mini { padding: 2px 8px; font-size: 11px; }
</style>
