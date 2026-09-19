import { useState, useCallback, useEffect } from "react";
import { llmService } from "../services/llm";
import type {
  LLMProviderConfig,
  LLMProviderInfo,
  LLMProviderFormData,
  LLMChatRequest,
  LLMChatResponse,
} from "../types/llm";

interface UseLLMReturn {
  configs: LLMProviderConfig[];
  providerInfo: LLMProviderInfo[];
  loading: boolean;
    error: Error | null;
  createConfig: (data: LLMProviderFormData) => Promise<LLMProviderConfig | null>;
  updateConfig: (id: number, data: Partial<LLMProviderFormData>) => Promise<boolean>;
  deleteConfig: (id: number) => Promise<boolean>;
  refreshConfigs: () => Promise<void>;
  chat: (req: LLMChatRequest) => Promise<LLMChatResponse | null>;
  testChat: (providerId: number, message: string) => Promise<{ content: string | null; error: string | null }>;
}

export function useLLM(): UseLLMReturn {
  const [configs, setConfigs] = useState<LLMProviderConfig[]>([]);
  const [providerInfo, setProviderInfo] = useState<LLMProviderInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const refreshConfigs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfgs, infos] = await Promise.all([
        llmService.listConfigs(),
        llmService.listProviders(),
      ]);
      setConfigs(cfgs);
      setProviderInfo(infos);
    } catch (err) {
      setError(new Error(err instanceof Error ? err.message : String(err)));
    } finally {
      setLoading(false);
    }
      }, []);

  useEffect(() => {
    refreshConfigs();
  }, [refreshConfigs]);

  const createConfig = useCallback(
    async (data: LLMProviderFormData): Promise<LLMProviderConfig | null> => {
      try {
        const config = await llmService.createConfig(data);
        await refreshConfigs();
        return config;
      } catch (err) {
        setError(new Error(err instanceof Error ? err.message : String(err)));
        return null;
      }
    },
    [refreshConfigs]
  );

  const updateConfig = useCallback(
    async (id: number, data: Partial<LLMProviderFormData>): Promise<boolean> => {
      try {
        await llmService.updateConfig(id, data);
        await refreshConfigs();
        return true;
      } catch (err) {
        setError(new Error(err instanceof Error ? err.message : String(err)));
        return false;
      }
    },
    [refreshConfigs]
  );

  const deleteConfig = useCallback(
    async (id: number): Promise<boolean> => {
      try {
        await llmService.deleteConfig(id);
        await refreshConfigs();
        return true;
      } catch (err) {
        setError(new Error(err instanceof Error ? err.message : String(err)));
        return false;
      }
    },
    [refreshConfigs]
  );

  const chat = useCallback(async (req: LLMChatRequest): Promise<LLMChatResponse | null> => {
    try {
      return await llmService.chat(req);
    } catch (err) {
      setError(new Error(err instanceof Error ? err.message : String(err)));
      return null;
    }
  }, []);

  const testChat = useCallback(
    async (providerId: number, message: string): Promise<{ content: string | null; error: string | null }> => {
      try {
        const config = await llmService.getConfig(providerId);
        if (!config) return { content: null, error: "Provider config not found" };
        const result = await llmService.chat({
          messages: [{ role: "user", content: message }],
          model: config.model,
          provider_name: config.provider_name,
        });
        return { content: result?.content ?? null, error: null };
      } catch (err) {
        const errorMsg = err instanceof Error
          ? err.message
          : err && typeof err === 'object' && 'message' in err
            ? (err as Record<string, unknown>).message as string
            : String(err);
        return { content: null, error: errorMsg };
      }
    },
    []
  );

  return {
    configs,
    providerInfo,
    loading,
    error,
    createConfig,
    updateConfig,
    deleteConfig,
    refreshConfigs,
    chat,
    testChat,
  };
}
