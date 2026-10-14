import { defineConfig } from '@playwright/test';
import os from 'node:os';
import path from 'node:path';

// A fresh backend (temporary database) and frontend just for the browser tests.
const API_PORT = 8765;
const WEB_PORT = 5765;
export const LLM_PORT = 8766;
// Decided once and handed to the test workers (which load this file again) through the environment.
const run = (process.env.NEXUS_E2E_RUN ??= path.join(os.tmpdir(), `nexus-e2e-${Date.now()}`));
const database = path.join(run, 'nexus.db');
// Emails (password reset) land here as files; the tests read the links from them.
export const MAILBOX = path.join(run, 'mail');
const python = process.env.NEXUS_PYTHON
  ?? (process.platform === 'win32' ? '../backend/.venv311/Scripts/python.exe' : '../backend/.venv311/bin/python');

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1, // the tests share one backend
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    // Locally reuse the installed Chrome; CI installs Playwright's Chromium.
    channel: process.env.CI ? undefined : 'chrome',
    trace: 'retain-on-failure',
  },
  projects: [
    // Signs up the owner on the fresh install and saves the session; the tests start signed in.
    { name: 'setup', testMatch: /auth\.setup\.ts/ },
    { name: 'app', dependencies: ['setup'], use: { storageState: 'e2e/.auth/owner.json' } },
  ],
  webServer: [
    {
      // Stands in for an AI provider, so chat can be tested without a real model.
      command: `"${python}" e2e/fake_llm.py ${LLM_PORT}`,
      url: `http://127.0.0.1:${LLM_PORT}/`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${API_PORT}/health`,
      env: {
        DATABASE_PATH: database,
        NEXUS_SECRET_KEY: 'e2e-secret',
        NEXUS_RAG_EMBEDDER: 'fake', // deterministic stand-in models: no 220 MB download in tests
        NEXUS_RAG_RERANKER: 'fake',
        NEXUS_REGISTRY_URL: `http://127.0.0.1:${LLM_PORT}`, // fake MCP Registry for the Marketplace
        CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
        NEXUS_MAIL_DIR: MAILBOX,
        NEXUS_APP_URL: `http://localhost:${WEB_PORT}`,
      },
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npx vite --port ${WEB_PORT} --strictPort`,
      url: `http://localhost:${WEB_PORT}`,
      env: { VITE_API_URL: `http://localhost:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
});
