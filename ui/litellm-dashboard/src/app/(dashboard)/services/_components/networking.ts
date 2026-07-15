import { getProxyBaseUrl, getGlobalLitellmHeaderName } from "@/components/networking";

import { ServiceAction, ServiceActionResult, ServiceListResponse } from "./types";

function authHeaders(accessToken: string): Record<string, string> {
  return {
    [getGlobalLitellmHeaderName()]: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  };
}

async function parseOrThrow<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function getServicesList(accessToken: string): Promise<ServiceListResponse> {
  const base = getProxyBaseUrl();
  const response = await fetch(`${base}/services/list`, {
    method: "GET",
    headers: authHeaders(accessToken),
  });
  return parseOrThrow<ServiceListResponse>(response);
}

export async function runServiceAction(
  accessToken: string,
  name: string,
  action: ServiceAction,
): Promise<ServiceActionResult> {
  const base = getProxyBaseUrl();
  const response = await fetch(`${base}/services/${encodeURIComponent(name)}/action`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: JSON.stringify({ action }),
  });
  return parseOrThrow<ServiceActionResult>(response);
}
