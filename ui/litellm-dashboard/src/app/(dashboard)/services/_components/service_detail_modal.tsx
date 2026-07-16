"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Modal, Button, Typography } from "antd";

import NotificationsManager from "@/components/molecules/notifications_manager";

import { getServiceDocs, runServiceCommand } from "./networking";
import { ServiceState } from "./types";

const { Title, Text } = Typography;

interface ServiceDetailModalProps {
  service: ServiceState | null;
  onClose: () => void;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

export default function ServiceDetailModal({ service, onClose }: ServiceDetailModalProps) {
  const [docs, setDocs] = useState<string | null>(null);
  const [docsError, setDocsError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    if (!service || !service.has_docs) return;
    let cancelled = false;
    getServiceDocs(service.name)
      .then((r) => {
        if (!cancelled) setDocs(r.markdown);
      })
      .catch((e) => {
        if (!cancelled) setDocsError(getErrorMessage(e));
      });
    return () => {
      cancelled = true;
    };
  }, [service]);

  const runCommand = useCallback(
    async (commandName: string) => {
      if (!service) return;
      setPending(commandName);
      try {
        const result = await runServiceCommand(service.name, commandName);
        if (result.success) {
          NotificationsManager.success(`${commandName}: ${result.message}`);
        } else {
          NotificationsManager.error({ message: `${commandName} failed`, description: result.message });
        }
      } catch (e) {
        NotificationsManager.error({ message: `${commandName} failed`, description: getErrorMessage(e) });
      } finally {
        setPending(null);
      }
    },
    [service],
  );

  const docsUnavailable = docs === null && !docsError;
  const showNoDocs = service !== null && docsUnavailable && !service.has_docs;

  return (
    <Modal
      title={service?.display_name ?? "Service"}
      open={service !== null}
      onCancel={onClose}
      footer={null}
      width={720}
    >
      {service && (
        <div className="flex flex-col gap-4">
          <div>
            <Text type="secondary" className="text-xs">
              {service.kind} · {service.endpoint} · {service.status}
            </Text>
            {service.web_url && (
              <div className="mt-1">
                <a
                  href={service.web_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:underline"
                >
                  {service.web_url}
                </a>
              </div>
            )}
          </div>

          {service.commands.length > 0 && (
            <div>
              <Title level={5}>Commands</Title>
              <div className="mt-2 flex flex-col gap-2">
                {service.commands.map((cmd) => (
                  <div key={cmd.name} className="flex items-center gap-2">
                    <Button
                      size="small"
                      loading={pending === cmd.name}
                      disabled={!service.control_enabled || pending !== null}
                      onClick={() => runCommand(cmd.name)}
                    >
                      {cmd.display_name}
                    </Button>
                    <Text type="secondary" className="text-xs">
                      {cmd.description}
                    </Text>
                  </div>
                ))}
              </div>
              {!service.control_enabled && (
                <Text type="warning" className="mt-1 block text-xs">
                  Commands are read-only until LITELLM_ENABLE_SERVICE_CONTROL=true.
                </Text>
              )}
            </div>
          )}

          <div>
            <Title level={5}>Documentation</Title>
            {docsError && (
              <Text type="secondary" className="text-xs">
                {docsError}
              </Text>
            )}
            {docs !== null && (
              <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words rounded bg-gray-50 p-3 text-xs">
                {docs}
              </pre>
            )}
            {showNoDocs && (
              <Text type="secondary" className="text-xs">
                No documentation found in the service directory.
              </Text>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}
