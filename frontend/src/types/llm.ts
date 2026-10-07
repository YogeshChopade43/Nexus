export type LLMProviderName = "openai" | "anthropic" | "ollama" | "grok" | "litellm" | "huggingface" | "groq" | "openrouter";

export interface LLMProviderConfig {
  id: number;
  provider_name: LLMProviderName;
  model: string;
  api_key?: string;
  base_url?: string;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface LLMProviderInfo {
  name: LLMProviderName;
  label: string;
  models: string[];
}

export interface LLMProviderFormData {
  provider_name: LLMProviderName;
  model: string;
  api_key?: string;
  base_url?: string;
  enabled?: boolean;
}

export interface LLMChatRequest {
  messages: Array<{ role: string; content: string }>;
  model?: string;
  provider_id?: number;
  provider_name?: string;
  temperature?: number;
  max_tokens?: number;
}

export interface LLMChatResponse {
  content: string;
  model: string;
  provider: string;
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  finish_reason?: string;
}
