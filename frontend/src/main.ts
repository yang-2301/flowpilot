import { createApp } from "vue";
import { createRouter, createWebHistory } from "vue-router";
import App from "./App.vue";
import "./style.css";
import WorkflowsView from "./views/WorkflowsView.vue";
import RunsView from "./views/RunsView.vue";
import RunDetailView from "./views/RunDetailView.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/workflows" },
    { path: "/workflows", component: WorkflowsView },
    { path: "/runs", component: RunsView },
    { path: "/runs/:id", component: RunDetailView },
  ],
});

createApp(App).use(router).mount("#app");
