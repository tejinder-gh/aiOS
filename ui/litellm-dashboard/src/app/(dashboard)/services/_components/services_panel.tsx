"use client";

import React, { useCallback, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Popconfirm, Tag, Typography } from "antd";

import NotificationsManager from "@/components/molecules/notifications_manager";

import { getServicesList, runServiceAction, deleteService } from "./networking";
import { ServiceAction, ServiceState, ServiceStatus } from "./types";
import AddServiceModal from "./add_service_modal";
import ServiceDetailModal from "./service_detail_modal";

const { Title, Text } = Typography;

const POLL_INTERVAL_MS = 5000;
const SERVICES_QUERY_KEY = ["services", "list"] as const;

interface ServicesPanelProps {
  accessToken: string | null;
}

const STATUS_COLOR: Record<ServiceStatus, string> = {
  running: "green",
  starting: "orange",
  stopped: "default",
  unknown: "orange",
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unknown error";
}

interface ServiceCardProps {
  service: ServiceState;
  controlEnabled: boolean;
  pending: ServiceAction | null;
  onAction: (name: string, action: ServiceAction) => void;
  onDetails: (service: ServiceState) => void;
  onDelete: (name: string) => void;
}

function ServiceCard({ service, controlEnabled, pending, onAction, onDetails, onDelete }: ServiceCardProps) {
  const busy = pending !== null;
  const statusOnly = service.dashboard_only;
  const actions: ServiceAction[] = ["start", "stop", "restart"];
  const isDisabled = (action: ServiceAction): boolean => {
    const stopBlocked = action === "stop" && service.prevent_stop;
    return !controlEnabled || busy || stopBlocked;
  };

  return (
    <Card size="small" className="flex flex-col gap-2">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Title level={5} className="!mb-0">
              {service.display_name}
            </Title>
            {statusOnly ? <Tag>status-only</Tag> : <Tag color={STATUS_COLOR[service.status]}>{service.status}</Tag>}
          </div>
          <Text type="secondary" className="text-xs">
            {service.description}
          </Text>
        </div>
        <Tag color="blue">{service.kind}</Tag>
      </div>

      <Text type="secondary" className="text-xs">
        {service.endpoint} · {service.detail}
      </Text>

      <div className="mt-2 flex flex-wrap gap-2">
        {!statusOnly &&
          actions.map((action) => (
            <Button
              key={action}
              size="small"
              loading={pending === action}
              disabled={isDisabled(action)}
              onClick={() => onAction(service.name, action)}
            >
              {action}
            </Button>
          ))}
        <Button size="small" type="link" onClick={() => onDetails(service)}>
          details
        </Button>
        <Popconfirm
          title={`Unregister ${service.display_name}?`}
          okText="Unregister"
          cancelText="Cancel"
          onConfirm={() => onDelete(service.name)}
        >
          <Button size="small" type="link" danger>
            remove
          </Button>
        </Popconfirm>
        {service.web_url && (
          <a
            href={service.web_url}
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto self-center text-xs text-blue-600 hover:underline"
          >
            open
          </a>
        )}
      </div>
    </Card>
  );
}

export default function ServicesPanel({ accessToken }: ServicesPanelProps) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Record<string, ServiceAction>>({});
  const [addOpen, setAddOpen] = useState(false);
  const [detailService, setDetailService] = useState<ServiceState | null>(null);

  const queryOptions = {
    queryKey: SERVICES_QUERY_KEY,
    queryFn: getServicesList,
    enabled: !!accessToken,
    refetchInterval: POLL_INTERVAL_MS,
  };
  const { data, isLoading, error, refetch } = useQuery(queryOptions);

  const services = data?.services ?? [];
  const controlEnabled = data?.control_enabled ?? false;

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: SERVICES_QUERY_KEY });
  }, [queryClient]);

  const handleAction = useCallback(
    async (name: string, action: ServiceAction) => {
      setPending((prev) => ({ ...prev, [name]: action }));
      try {
        const result = await runServiceAction(name, action);
        if (result.success) {
          NotificationsManager.success(`${action} ${name}: ${result.message}`);
        } else {
          NotificationsManager.error({ message: `${action} ${name} failed`, description: result.message });
        }
      } catch (e) {
        NotificationsManager.error({ message: `${action} ${name} failed`, description: getErrorMessage(e) });
      } finally {
        setPending((prev) => {
          const { [name]: _removed, ...rest } = prev;
          return rest;
        });
        invalidate();
      }
    },
    [invalidate],
  );

  const handleDelete = useCallback(
    async (name: string) => {
      try {
        await deleteService(name);
        NotificationsManager.success(`Unregistered ${name}`);
        invalidate();
      } catch (e) {
        NotificationsManager.error({ message: `Could not unregister ${name}`, description: getErrorMessage(e) });
      }
    },
    [invalidate],
  );

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <Title level={4} className="!mb-0">
            Services
          </Title>
          <Text type="secondary">Start, stop and monitor the local services your LiteLLM hub depends on.</Text>
        </div>
        <div className="flex gap-2">
          <Button type="primary" onClick={() => setAddOpen(true)} disabled={!accessToken}>
            Add service
          </Button>
          <Button onClick={() => void refetch()}>Refresh</Button>
        </div>
      </div>

      {!controlEnabled && !isLoading && (
        <Card size="small" className="mb-4 border-l-4 border-amber-400">
          <Text>
            Control actions are read-only. Set <code>LITELLM_ENABLE_SERVICE_CONTROL=true</code> in the proxy environment
            and restart to enable start/stop/restart.
          </Text>
        </Card>
      )}

      {error && (
        <Card size="small" className="mb-4 border-l-4 border-red-400">
          <Text type="danger">{getErrorMessage(error)}</Text>
        </Card>
      )}

      {isLoading ? (
        <Text>Loading services…</Text>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {services.map((service) => (
            <ServiceCard
              key={service.name}
              service={service}
              controlEnabled={controlEnabled}
              pending={pending[service.name] ?? null}
              onAction={handleAction}
              onDetails={setDetailService}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      <AddServiceModal open={addOpen} onClose={() => setAddOpen(false)} onRegistered={invalidate} />
      <ServiceDetailModal
        key={detailService?.name ?? "none"}
        service={detailService}
        onClose={() => setDetailService(null)}
      />
    </div>
  );
}
