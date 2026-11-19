<script setup lang="ts">
</script>

<template>
  <div class="topnav">
    <div class="brand">Flow<span class="accent">Pilot</span></div>
    <nav class="links">
      <router-link to="/workflows">Workflows</router-link>
      <router-link to="/runs">Runs</router-link>
    </nav>
    <div class="spacer" />
    <span class="muted">automation console</span>
  </div>
  <main>
    <router-view />
  </main>
</template>

<style scoped>
.topnav {
  display: flex; align-items: center; gap: 24px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 10px 24px;
}
.brand { font-weight: 700; font-size: 17px; }
.brand .accent { color: var(--accent); }
.links { display: flex; gap: 16px; }
.links a { color: var(--muted); text-decoration: none; font-weight: 550; }
.links a.router-link-active { color: var(--accent); }
.spacer { flex: 1; }
main { max-width: 1080px; margin: 24px auto; padding: 0 24px; }
</style>
