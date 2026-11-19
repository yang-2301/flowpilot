declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<{}, {}, any>;
  export default component;
}

export interface StepDef {
  type: "transform" | "http_request" | "llm" | "condition";
  name: string;
  config: Record<string, any>;
  max_attempts: number;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  trigger_type: "webhook" | "interval";
  trigger_config: Record<string, any>;
  steps: StepDef[];
  enabled: boolean;
  created_at: string;
}

export interface StepRun {
  idx: number;
  name: string;
  type: string;
  status: "ok" | "failed" | "skipped";
  output: any;
  error: string | null;
  attempts: number;
  duration_ms: number;
}

export interface Run {
  id: string;
  workflow_id: string;
  status: "running" | "success" | "failed" | "dead" | "skipped";
  trigger_payload: Record<string, any>;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  replay_of: string | null;
  steps?: StepRun[];
}
