import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi, beforeEach } from "vitest";
import ServicesPanel from "../src/app/(dashboard)/services/_components/services_panel";
import * as networking from "../src/app/(dashboard)/services/_components/networking";
import { ServiceState } from "../src/app/(dashboard)/services/_components/types";

vi.mock("../src/app/(dashboard)/services/_components/networking", () => ({
  getServicesList: vi.fn(),
  runServiceAction: vi.fn(),
}));

const ollama: ServiceState = {
  name: "ollama",
  display_name: "Ollama",
  description: "Local model runtime",
  docs_url: "https://ollama.com",
  kind: "brew",
  status: "running",
  healthy: true,
  endpoint: "localhost:11434",
  detail: "listening",
  control_enabled: true,
  prevent_stop: false,
  dashboard_only: false,
};

const postgres: ServiceState = {
  name: "postgres",
  display_name: "PostgreSQL",
  description: "Proxy database",
  docs_url: null,
  kind: "brew",
  status: "running",
  healthy: true,
  endpoint: "localhost:5432",
  detail: "listening",
  control_enabled: true,
  prevent_stop: true,
  dashboard_only: false,
};

const adk: ServiceState = {
  name: "adk",
  display_name: "ADK",
  description: "Status-only app",
  docs_url: null,
  kind: "command",
  status: "unknown",
  healthy: false,
  endpoint: "localhost:1",
  detail: "status-only",
  control_enabled: false,
  prevent_stop: false,
  dashboard_only: true,
};

function mockList(services: ServiceState[]) {
  vi.mocked(networking.getServicesList).mockResolvedValue({ control_enabled: true, services });
}

beforeEach(() => {
  vi.resetAllMocks();
  mockList([ollama, postgres, adk]);
});

test("renders services after loading", async () => {
  render(<ServicesPanel accessToken="test-token" />);
  expect(screen.getByText("Loading services…")).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText("Ollama")).toBeInTheDocument());
  expect(screen.getByText("PostgreSQL")).toBeInTheDocument();
  expect(screen.getByText("ADK")).toBeInTheDocument();
});

test("a normal service exposes start, stop and restart", async () => {
  mockList([ollama]);
  render(<ServicesPanel accessToken="test-token" />);
  await waitFor(() => expect(screen.getByText("Ollama")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "start" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "stop" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "restart" })).toBeInTheDocument();
});

test("a prevent_stop service keeps start but hides stop and restart", async () => {
  mockList([postgres]);
  render(<ServicesPanel accessToken="test-token" />);
  await waitFor(() => expect(screen.getByText("PostgreSQL")).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "start" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "stop" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "restart" })).not.toBeInTheDocument();
});

test("a dashboard_only service renders no action buttons", async () => {
  mockList([adk]);
  render(<ServicesPanel accessToken="test-token" />);
  await waitFor(() => expect(screen.getByText("ADK")).toBeInTheDocument());
  expect(screen.queryByRole("button", { name: "start" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "stop" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "restart" })).not.toBeInTheDocument();
  expect(screen.getByText("status-only")).toBeInTheDocument();
});

test("clicking an action calls runServiceAction with the right args", async () => {
  mockList([ollama]);
  const actionResult = {
    name: "ollama",
    action: "restart",
    success: true,
    message: "ok",
    status: "unknown",
  } as const;
  vi.mocked(networking.runServiceAction).mockResolvedValue(actionResult);
  render(<ServicesPanel accessToken="test-token" />);
  await waitFor(() => expect(screen.getByText("Ollama")).toBeInTheDocument());

  fireEvent.click(screen.getByRole("button", { name: "restart" }));

  await waitFor(() =>
    expect(networking.runServiceAction).toHaveBeenCalledWith("test-token", "ollama", "restart"),
  );
});
