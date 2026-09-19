import { useEffect } from 'react';
import { useLocalStorage } from './useUtils';

interface UseSettingsReturn {
  theme: 'dark' | 'light' | 'system';
  setTheme: (theme: 'dark' | 'light' | 'system') => void;
}

export function useSettings(): UseSettingsReturn {
  const [theme, setTheme] = useLocalStorage<'dark' | 'light' | 'system'>('nexus-theme', 'dark');

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('light', 'dark');
    if (theme === 'system') {
      const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      root.classList.add(prefersDark ? 'dark' : 'light');
    } else {
      root.classList.add(theme);
    }
  }, [theme]);

  return { theme, setTheme };
}
