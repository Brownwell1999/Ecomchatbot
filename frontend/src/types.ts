export type Role = "user" | "assistant";

export interface Product {
  id: number;
  name: string;
  brand: string;
  category: string;
  price: number;
  rating: number;
  stock: number;
}

export interface Order {
  id: number;
  status: string;
  total: number;
  carrier: string | null;
  trackingNumber: string | null;
  placedAt: string;
  deliveredAt: string | null;
  items: { name: string; quantity: number; unitPrice: number }[];
}

export interface Source {
  source: string;
  section: string;
  chunkId: string;
  score: number;
}

export interface DebugInfo {
  requestId: string;
  promptVersion: string;
  latencyMs: number;
  intent: string;
  confidence: number;
  nluSource: string;
  entities: Record<string, unknown>;
  route: string;
  fallbackUsed: boolean;
  toolCalls: { name: string; args: Record<string, unknown>; ok: boolean; latencyMs: number }[];
  llmCalls: { step: string; provider: string; model: string; latencyMs: number; inputTokens: number | null; outputTokens: number | null }[];
  retrievedChunks: { chunkId: string; collection: string; section: string; score: number; used: boolean }[];
  guardrails: { name: string; stage: string; passed: boolean; action: string; score: number | null; detail: string }[];
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  createdAt: string;
  products?: Product[];
  order?: Order | null;
  sources?: Source[];
  suggestions?: string[];
  status?: "sending" | "streaming" | "failed";
  debug?: DebugInfo | null;
}

export interface ChatError {
  code: string;
  message: string;
}

export interface User {
  id: number;
  email: string;
  fullName: string;
}
