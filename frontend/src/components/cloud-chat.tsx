"use client";

import { BackendStatus } from "@/components/backend-status";
import { usePersistedModel } from "@/hooks/use-persisted-model";
import { MODEL_OPTIONS } from "@/lib/models";
import { STARTERS } from "@/lib/starters";
import {
  AgentInterface,
  fetchLLM,
  ModelSwitcher,
  openuiLibrary,
  useOpenuiCloudStorage,
  vercelAIAdapter,
  vercelAIMessageFormat,
} from "@openuidev/react-ui";

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
}: {
  selectedModel: string;
  setSelectedModel: (model: string) => void;
}) {
  return (
    <div className="flytbase-thread-toolbar max-w-full min-w-0">
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
  const llm = fetchLLM({
    url: "/api/chat",
    streamAdapter: vercelAIAdapter(),
    messageFormat: vercelAIMessageFormat,
    body: { model: selectedModel },
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
        componentLibrary={openuiLibrary}
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
            <ModelToolbar selectedModel={selectedModel} setSelectedModel={setSelectedModel} />
          }
        />
        <AgentInterface.Welcome
          title="Asset intelligence for field operators"
          description="Ask about well status, inspections, maintenance, and SOPs. Answers use the FlytBase backend and render as structured UI."
          starterVariant="short"
        />
      </AgentInterface>
    </div>
  );
}
