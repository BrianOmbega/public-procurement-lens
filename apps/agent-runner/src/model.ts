import dotenv from 'dotenv';

dotenv.config();

export interface LocalModelRequest {
  prompt: string;
  maxTokens?: number;
}

export interface LocalModelResponse {
  model: string;
  response: string;
  provider: 'ollama';
}

export const runLocalModel = async ({ prompt, maxTokens = 256 }: LocalModelRequest): Promise<LocalModelResponse> => {
  const modelName = process.env.OLLAMA_MODEL ?? 'llama3.2:3b';
  const baseUrl = process.env.OLLAMA_BASE_URL ?? 'http://localhost:11434';

  if (!prompt.trim()) {
    throw new Error('Local model prompt cannot be empty.');
  }

  const responseText = `Using ${modelName} via ${baseUrl}: ${prompt.slice(0, 120)}${prompt.length > 120 ? '…' : ''}`;

  return {
    model: modelName,
    response: responseText,
    provider: 'ollama'
  };
};
