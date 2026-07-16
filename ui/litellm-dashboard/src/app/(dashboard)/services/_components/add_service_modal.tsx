"use client";

import React, { useCallback, useState } from "react";
import { Modal, Form, Input, InputNumber, Checkbox, Button, Typography } from "antd";

import NotificationsManager from "@/components/molecules/notifications_manager";
import { ApiError } from "@/lib/http/client";

import { previewImport, registerService } from "./networking";
import { ConnectionInfo, ImportPreview, ManagedServiceSpec } from "./types";

const { Text } = Typography;

interface AddServiceModalProps {
  open: boolean;
  onClose: () => void;
  onRegistered: () => void;
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Unexpected error";
}

function suggestedPortFromError(error: unknown): number | null {
  if (!(error instanceof ApiError)) return null;
  const detail = (error.body as { detail?: { suggested_port?: number } } | undefined)?.detail;
  return typeof detail?.suggested_port === "number" ? detail.suggested_port : null;
}

function specFromPreview(preview: ImportPreview, port: number): ManagedServiceSpec {
  return {
    name: preview.name,
    display_name: preview.display_name,
    description: preview.description,
    docs_url: null,
    kind: preview.kind,
    health_host: preview.health_host,
    health_port: port,
    start_cmd: preview.start_cmd,
    stop_cmd: preview.stop_cmd,
    restart_cmd: preview.restart_cmd,
    prevent_stop: false,
    commands: preview.commands,
    web_url: `http://${preview.health_host}:${port}`,
    docs_path: preview.docs_path,
    working_dir: preview.working_dir,
  };
}

export default function AddServiceModal({ open, onClose, onRegistered }: AddServiceModalProps) {
  const [path, setPath] = useState("");
  const [scanning, setScanning] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [port, setPort] = useState<number>(0);
  const [generateKey, setGenerateKey] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [connection, setConnection] = useState<ConnectionInfo | null>(null);

  const reset = useCallback(() => {
    setPath("");
    setPreview(null);
    setPort(0);
    setGenerateKey(false);
    setConnection(null);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [onClose, reset]);

  const handleScan = useCallback(async () => {
    if (!path.trim()) return;
    setScanning(true);
    setConnection(null);
    try {
      const result = await previewImport(path.trim());
      setPreview(result);
      setPort(result.conflicts.length > 0 ? result.suggested_port : result.detected_port);
    } catch (e) {
      setPreview(null);
      NotificationsManager.error({ message: "Could not scan directory", description: getErrorMessage(e) });
    } finally {
      setScanning(false);
    }
  }, [path]);

  const handleRegister = useCallback(async () => {
    if (!preview) return;
    setSubmitting(true);
    try {
      const spec = specFromPreview(preview, port);
      const response = await registerService(spec, generateKey);
      NotificationsManager.success(`Registered ${spec.display_name}`);
      onRegistered();
      if (response.connection_info) {
        setConnection(response.connection_info);
      } else {
        handleClose();
      }
    } catch (e) {
      const suggested = suggestedPortFromError(e);
      if (suggested !== null) setPort(suggested);
      NotificationsManager.error({ message: "Could not register service", description: getErrorMessage(e) });
    } finally {
      setSubmitting(false);
    }
  }, [generateKey, handleClose, onRegistered, port, preview]);

  const copy = useCallback((value: string) => {
    void navigator.clipboard.writeText(value).then(() => NotificationsManager.success("Copied"));
  }, []);

  return (
    <Modal title="Add service" open={open} onCancel={handleClose} footer={null} width={640} destroyOnClose>
      {connection ? (
        <div className="flex flex-col gap-3">
          <Text>
            Route this app&apos;s LLM traffic through the proxy by setting these in its environment. Copy the key now;
            it is shown only once.
          </Text>
          <pre className="whitespace-pre-wrap break-all rounded bg-gray-100 p-3 text-xs">{connection.env_snippet}</pre>
          <div className="flex gap-2">
            <Button size="small" onClick={() => copy(connection.env_snippet)}>
              Copy env
            </Button>
            <Button size="small" onClick={() => copy(connection.api_key)}>
              Copy key
            </Button>
            <Button size="small" type="primary" className="ml-auto" onClick={handleClose}>
              Done
            </Button>
          </div>
        </div>
      ) : (
        <Form layout="vertical" onFinish={handleRegister}>
          <Form.Item label="Project directory" required>
            <div className="flex gap-2">
              <Input
                value={path}
                placeholder="/opt/Developer/SourceCode/AI/Perplexica"
                onChange={(e) => setPath(e.target.value)}
                onPressEnter={handleScan}
              />
              <Button onClick={handleScan} loading={scanning}>
                Scan
              </Button>
            </div>
          </Form.Item>

          {preview && (
            <>
              <Form.Item label="Name">
                <Input value={preview.name} disabled />
              </Form.Item>
              <div className="mb-3 flex gap-4">
                <Text type="secondary" className="text-xs">
                  kind: {preview.kind}
                </Text>
                <Text type="secondary" className="text-xs">
                  detected port: {preview.detected_port}
                </Text>
                <Text type="secondary" className="text-xs">
                  commands: {preview.commands.length}
                </Text>
              </div>
              {preview.conflicts.length > 0 && (
                <div className="mb-3 rounded border-l-4 border-amber-400 bg-amber-50 p-2">
                  <Text type="warning" className="text-xs">
                    Port {preview.detected_port} is already used by {preview.conflicts.join(", ")}. Suggested free port:{" "}
                    {preview.suggested_port}.
                  </Text>
                </div>
              )}
              <Form.Item label="Health port">
                <InputNumber value={port} min={1} max={65535} onChange={(v) => setPort(Number(v ?? 0))} />
              </Form.Item>
              <Form.Item>
                <Checkbox checked={generateKey} onChange={(e) => setGenerateKey(e.target.checked)}>
                  Route this app&apos;s LLM calls through the proxy (generate a virtual key)
                </Checkbox>
              </Form.Item>
              <div className="flex justify-end gap-2">
                <Button onClick={handleClose}>Cancel</Button>
                <Button type="primary" htmlType="submit" loading={submitting}>
                  Register
                </Button>
              </div>
            </>
          )}
        </Form>
      )}
    </Modal>
  );
}
