"use client";

import useAuthorized from "@/app/(dashboard)/hooks/useAuthorized";

import ServicesPanel from "./_components/services_panel";

export default function Services() {
  const { accessToken } = useAuthorized();
  return <ServicesPanel accessToken={accessToken} />;
}
