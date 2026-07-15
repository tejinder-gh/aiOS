"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, Grid, Text, Title } from "@tremor/react";
import { RefreshIcon } from "@heroicons/react/outline";

import NotificationsManager from "@/components/molecules/notifications_manager";

import { getServicesList, runServiceAction } from "./networking";
import { ServiceAction, ServiceState, ServiceStatus } from "./types";

const POLL_INTERVAL_MS = 5000;

interface ServicesPanelProps {
  accessToken: string | null;
}

const STATUS_COLOR: Record<ServiceStatus, "emerald" | "gray" | "amber"> = {
  running: "emerald",
  stopped: "gray",
  unknown: "amber",
};

function StatusBadge({ status }: { status: ServiceStatus }) {
  return <Badge color={STATUS_COLOR[status]}>{status}</Badge>;
}

function ServiceCard({
  service,
  controlEnabled,
  pending,
  onAction,
}: {
  service: ServiceState;
  controlEnabled: boolean;
  pending: ServiceAction | null;
  onAction: (name: string, action: ServiceAction) => void;
}) {
  const disabled = !controlEnabled || pending !== null;
  const actions: ServiceAction[] = service.prevent_stop ? ["start"] : ["start", "stop", "restart"];

  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Title>{service.display_name}</Title>
            <StatusBadge status={service.status} />
          </div>
          <Text className="mt-1">{service.description}</Text>
        </div>
        <Badge color="blue">{service.kind}</Badge>
      </div>

      <Text className="text-xs text-gray-500">
        {service.endpoint} · {service.detail}
      </Text>

      <div className="flex gap-2">
        {service.dashboard_only ? (
          <Text className="text-xs text-gray-500 self-center">status-only</Text>
        ) : (
          actions.map((action) => (
            <Button
              key={action}
              size="xs"
              variant={action === "stop" ? "secondary" : "primary"}
              disabled={disabled}
              loading={pending === action}
              onClick={() => onAction(service.name, action)}
            >
              {action}
            </Button>
          ))
        )}
        {service.docs_url && (
          <a
            href={service.docs_url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto self-center text-xs text-blue-600 hover:underline"
          >
            docs
          </a>
        )}
      </div>
    </Card>
  );
}

export default function ServicesPanel({ accessToken }: ServicesPanelProps) {
  const [services, setServices] = useState<ServiceState[]>([]);
  const [controlEnabled, setControlEnabled] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Record<string, ServiceAction>>({});

  const refresh = useCallback(async () => {
    if (!accessToken) return;
    try {
      const data = await getServicesList(accessToken);
      setServices(data.services);
      setControlEnabled(data.control_enabled);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load services");
    } finally {
      setLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const handleAction = useCallback(
    async (name: string, action: ServiceAction) => {
      if (!accessToken) return;
      setPending((prev) => ({ ...prev, [name]: action }));
      try {
        const result = await runServiceAction(accessToken, name, action);
        if (result.success) {
          NotificationsManager.success(`${action} ${name}: ${result.message}`);
        } else {
          NotificationsManager.error({ message: `${action} ${name} failed`, description: result.message });
        }
      } catch (e) {
        NotificationsManager.error({
          message: `${action} ${name} failed`,
          description: e instanceof Error ? e.message : "Unknown error",
        });
      } finally {
        setPending((prev) => {
          const { [name]: _removed, ...rest } = prev;
          return rest;
        });
        await refresh();
      }
    },
    [accessToken, refresh],
  );

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Title>Services</Title>
          <Text>Start, stop and monitor the local services your LiteLLM hub depends on.</Text>
        </div>
        <Button icon={RefreshIcon} variant="secondary" onClick={refresh}>
          Refresh
        </Button>
      </div>

      {!controlEnabled && !loading && (
        <Card className="mb-4 border-l-4 border-amber-400">
          <Text>
            Control actions are read-only. Set <code>LITELLM_ENABLE_SERVICE_CONTROL=true</code> in the proxy environment
            and restart to enable start/stop/restart.
          </Text>
        </Card>
      )}

      {error && (
        <Card className="mb-4 border-l-4 border-red-400">
          <Text className="text-red-600">{error}</Text>
        </Card>
      )}

      {loading ? (
        <Text>Loading services…</Text>
      ) : (
        <Grid numItems={1} numItemsMd={2} numItemsLg={3} className="gap-4">
          {services.map((service) => (
            <ServiceCard
              key={service.name}
              service={service}
              controlEnabled={controlEnabled}
              pending={pending[service.name] ?? null}
              onAction={handleAction}
            />
          ))}
        </Grid>
      )}
    </div>
  );
}
