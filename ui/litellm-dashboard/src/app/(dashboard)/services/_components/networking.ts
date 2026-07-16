import { fetchClient } from "@/lib/http/api";

import {
  ImportPreview,
  ManagedServiceSpec,
  PortsResponse,
  RegisterServiceResponse,
  ServiceAction,
  ServiceActionResult,
  ServiceCommandResult,
  ServiceDocsResponse,
  ServiceListResponse,
} from "./types";

export async function getServicesList(): Promise<ServiceListResponse> {
  const { data } = await fetchClient.GET("/services/list");
  return data as ServiceListResponse;
}

export async function getPorts(): Promise<PortsResponse> {
  const { data } = await fetchClient.GET("/services/ports");
  return data as PortsResponse;
}

export async function runServiceAction(name: string, action: ServiceAction): Promise<ServiceActionResult> {
  const { data } = await fetchClient.POST("/services/{name}/action", {
    params: { path: { name } },
    body: { action },
  });
  return data as ServiceActionResult;
}

export async function runServiceCommand(name: string, commandName: string): Promise<ServiceCommandResult> {
  const { data } = await fetchClient.POST("/services/{name}/command/{command_name}", {
    params: { path: { name, command_name: commandName } },
  });
  return data as ServiceCommandResult;
}

export async function previewImport(path: string): Promise<ImportPreview> {
  const { data } = await fetchClient.POST("/services/import/preview", { body: { path } });
  return data as ImportPreview;
}

export async function registerService(
  spec: ManagedServiceSpec,
  generateProxyKey: boolean,
): Promise<RegisterServiceResponse> {
  const { data } = await fetchClient.POST("/services/register", {
    body: { spec, generate_proxy_key: generateProxyKey },
  });
  return data as RegisterServiceResponse;
}

export async function deleteService(name: string): Promise<ServiceListResponse> {
  const { data } = await fetchClient.DELETE("/services/{name}", { params: { path: { name } } });
  return data as ServiceListResponse;
}

export async function getServiceDocs(name: string): Promise<ServiceDocsResponse> {
  const { data } = await fetchClient.GET("/services/{name}/docs", { params: { path: { name } } });
  return data as ServiceDocsResponse;
}
