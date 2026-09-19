import { api } from "../services/api";
import type {
  LLMProviderConfig,
  LLMProviderInfo,
  LLMProviderFormData,
  LLMChatRequest,
  LLMChatResponse,
} from "../types/llm";

export const llmService = {
  async listProviders(): Promise<LLMProviderInfo[]> {
    return api.get<LLMProviderInfo[]>("/api/llm/providers");
  },

  async listConfigs(): Promise<LLMProviderConfig[]> {
    return api.get<LLMProviderConfig[]>("/api/llm/");
  },

  async createConfig(data: LLMProviderFormData): Promise<LLMProviderConfig> {
    return api.post<LLMProviderConfig>("/api/llm/", data);
  },

  async updateConfig(id: number, data: Partial<LLMProviderFormData>): Promise<LLMProviderConfig> {
    return api.put<LLMProviderConfig>(`/api/llm/${id}`, data);
  },

  async deleteConfig(id: number): Promise<void> {
    return api.delete(`/api/llm/${id}`);
  },

  async getConfig(id: number): Promise<LLMProviderConfig> {
    return api.get<LLMProviderConfig>(`/api/llm/${id}`);
  },

  async chat(req: LLMChatRequest): Promise<LLMChatResponse> {
    return api.post<LLMChatResponse>("/api/llm/chat", req);
  },
};
