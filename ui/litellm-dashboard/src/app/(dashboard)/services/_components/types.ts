import type { components } from "@/lib/http/schema";

type Schemas = components["schemas"];

export type ServiceState = Schemas["ServiceState"];
export type ServiceKind = ServiceState["kind"];
export type ServiceStatus = ServiceState["status"];
export type ServiceListResponse = Schemas["ServiceListResponse"];
export type ServiceActionRequest = Schemas["ServiceActionRequest"];
export type ServiceAction = ServiceActionRequest["action"];
export type ServiceActionResult = Schemas["ServiceActionResult"];
export type ServiceCommandResult = Schemas["ServiceCommandResult"];
export type ServiceCommandInfo = Schemas["ServiceCommandInfo"];
export type PortsResponse = Schemas["PortsResponse"];
export type PortAllocation = Schemas["PortAllocation"];
export type ImportPreview = Schemas["ImportPreview"];
export type ImportRequest = Schemas["ImportRequest"];
export type DetectedCommand = Schemas["DetectedCommand"];
export type ManagedServiceSpec = Schemas["ManagedServiceSpec"];
export type RegisterServiceRequest = Schemas["RegisterServiceRequest"];
export type RegisterServiceResponse = Schemas["RegisterServiceResponse"];
export type ConnectionInfo = Schemas["ConnectionInfo"];
export type ServiceDocsResponse = Schemas["ServiceDocsResponse"];
