"use client";

import React from "react";
import { useParams } from "next/navigation";
import ChatVista from "@/components/ChatVista";

export default function ConversationPage() {
  const params = useParams();
  const id = params?.id ? decodeURIComponent(String(params.id)) : null;

  return <ChatVista conversationId={id} />;
}
