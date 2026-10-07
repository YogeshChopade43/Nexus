import { useCallback, useEffect, useSyncExternalStore } from 'react';

type Theme = 'dark' | 'light' | 'system';

const STORAGE_KEY = 'nexus-theme';
const listeners = new Set<() => void>();

function readTheme(): Theme {
  try {
    const value = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '"dark"');
    return value === 'light' || value === 'system' ? value : 'dark';
  } catch {
    return 'dark';
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function applyTheme(theme: Theme) {
  const dark = theme === 'system' ? window.matchMedia('(prefers-color-scheme: dark)').matches : theme === 'dark';
  document.documentElement.classList.toggle('light', !dark);
  document.documentElement.classList.toggle('dark', dark);
}

interface UseSettingsReturn {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

/** Theme preference shared by every component that uses it (Header, Settings). */
export function useSettings(): UseSettingsReturn {
  const theme = useSyncExternalStore(subscribe, readTheme, () => 'dark' as Theme);

  const setTheme = useCallback((next: Theme) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // Storage can be unavailable (private mode); the theme still applies for this session.
    }
    applyTheme(next);
    listeners.forEach(listener => listener());
  }, []);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== 'system') return;
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => applyTheme('system');
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [theme]);

  return { theme, setTheme };
}
