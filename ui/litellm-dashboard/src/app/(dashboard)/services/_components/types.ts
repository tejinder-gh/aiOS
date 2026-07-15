export type ServiceKind = "brew" | "docker_compose" | "command";
export type ServiceStatus = "running" | "stopped" | "unknown";
export type ServiceAction = "start" | "stop" | "restart";

export interface ServiceState {
  name: string;
  display_name: string;
  description: string;
  docs_url: string | null;
  kind: ServiceKind;
  status: ServiceStatus;
  healthy: boolean;
  endpoint: string;
  detail: string;
  control_enabled: boolean;
}

export interface ServiceListResponse {
  control_enabled: boolean;
  services: ServiceState[];
}

export interface ServiceActionResult {
  name: string;
  action: ServiceAction;
  success: boolean;
  message: string;
  status: ServiceStatus;
}
