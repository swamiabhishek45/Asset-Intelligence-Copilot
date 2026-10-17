"use client";

import React, { useState, useEffect } from "react";
import { BackendStatus } from "@/components/backend-status";
import { UserPicker } from "@/components/user-picker";
import { usePersistedModel } from "@/hooks/use-persisted-model";
import { MODEL_OPTIONS } from "@/lib/models";
import { STARTERS } from "@/lib/starters";
import {
  AgentInterface,
  fetchLLM,
  ModelSwitcher,
  useOpenuiCloudStorage,
  vercelAIAdapter,
  vercelAIMessageFormat,
} from "@openuidev/react-ui";
import { flytbaseLibrary } from "@/lib/flytbase-library";

const flytbaseTheme = {
  mode: "light" as const,
  colors: {
    background: "#ffffff",
    foreground: "#0a0a0a",
    muted: "#f4f4f5",
    mutedForeground: "#52525b",
    border: "#e4e4e7",
    primary: "#0a0a0a",
    primaryForeground: "#fafafa",
  },
};

function ModelToolbar({
  selectedModel,
  setSelectedModel,
  selectedUser,
  setSelectedUser,
}: {
  selectedModel: string;
  setSelectedModel: (model: string) => void;
  selectedUser: string;
  setSelectedUser: (user: string) => void;
}) {
  return (
    <div className="flytbase-thread-toolbar flex items-center gap-3 max-w-full min-w-0">
      <UserPicker selectedUser={selectedUser} onUserChange={setSelectedUser} />
      <ModelSwitcher
        models={MODEL_OPTIONS}
        value={selectedModel}
        onValueChange={setSelectedModel}
      />
    </div>
  );
}

export default function CloudChat() {
  const [selectedModel, setSelectedModel] = usePersistedModel();
  const [selectedUser, setSelectedUser] = useState<string>("U-201");

  useEffect(() => {
    const saved = localStorage.getItem("flytbase_active_user");
    if (saved) setSelectedUser(saved);
  }, []);

  const handleUserChange = (u: string) => {
    setSelectedUser(u);
    localStorage.setItem("flytbase_active_user", u);
  };

  const llm = fetchLLM({
    url: "/api/chat",
    streamAdapter: vercelAIAdapter(),
    messageFormat: vercelAIMessageFormat,
    body: { model: selectedModel, userId: selectedUser },
  });

  const storage = useOpenuiCloudStorage({
    token: "/api/frontend-token",
    apiBaseUrl: "https://api.thesys.dev",
    features: { artifact: false },
  });

  return (
    <div className="h-full min-h-0 bg-background text-foreground">
      <AgentInterface
        storage={storage}
        llm={llm}
        componentLibrary={flytbaseLibrary}
        theme={flytbaseTheme}
        starters={STARTERS}
      >
        <AgentInterface.SidebarHeader
          logo={
            <img
              src="/flytbase-mark.svg"
              alt=""
              width={30}
              height={30}
              className="rounded-sm"
            />
          }
          agentName={
            <div className="flex min-w-0 flex-col gap-0.5 leading-tight">
              <span className="truncate text-sm font-semibold tracking-tight">FlytBase</span>
              <span className="text-muted-foreground truncate text-[10px] font-normal uppercase tracking-[0.14em]">
                Asset Copilot
              </span>
            </div>
          }
        />
        <AgentInterface.SidebarFooter>
          <BackendStatus />
        </AgentInterface.SidebarFooter>
        <AgentInterface.MobileHeader
          agentName="FlytBase Copilot"
          logo={
            <img src="/flytbase-mark.svg" alt="" width={32} height={32} className="rounded-md" />
          }
        />
        <AgentInterface.ThreadHeader
          showChatTitle={false}
          end={
            <ModelToolbar
              selectedModel={selectedModel}
              setSelectedModel={setSelectedModel}
              selectedUser={selectedUser}
              setSelectedUser={handleUserChange}
            />
          }
        />
        <AgentInterface.Welcome
          title="Asset intelligence for field operators"
          description="Ask for status cards, charts, tables, heatmaps, and maps. Answers use the FlytBase backend and render as dynamic OpenUI."
          starterVariant="short"
        />
      </AgentInterface>
    </div>
  );
}
