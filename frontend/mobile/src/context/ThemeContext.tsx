import React, { createContext, useState, useEffect, useContext } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';

export const themeColors = {
  dark: {
    bg: '#0A0A0F',
    surface: '#12121A',
    surfaceVariant: '#1E1E2E',
    text: '#FFFFFF',
    textSecondary: '#A0A0B8',
    border: '#2A2A35',
    primary: '#7B61FF',
    primarySoft: 'rgba(123, 97, 255, 0.2)',
    success: '#00C851',
    successSoft: 'rgba(0, 200, 81, 0.2)',
    error: '#FF3B3B',
    errorSoft: 'rgba(255, 59, 59, 0.2)',
    warning: '#FFB300',
    warningSoft: 'rgba(255, 179, 0, 0.2)',
    cyan: '#00D4FF',
  },
  light: {
    bg: '#F0F4FF',
    surface: '#FFFFFF',
    surfaceVariant: '#E2E8F0',
    text: '#0A0A1A',
    textSecondary: '#4A5568',
    border: '#CBD5E1',
    primary: '#7B61FF',
    primarySoft: 'rgba(123, 97, 255, 0.1)',
    success: '#00C851',
    successSoft: 'rgba(0, 200, 81, 0.1)',
    error: '#FF3B3B',
    errorSoft: 'rgba(255, 59, 59, 0.1)',
    warning: '#FFB300',
    warningSoft: 'rgba(255, 179, 0, 0.1)',
    cyan: '#00D4FF',
  }
};

type ThemeContextType = {
  isDarkMode: boolean;
  toggleTheme: (value: boolean) => void;
  geminiApiKey: string;
  setGeminiApiKey: (key: string) => void;
  apiBaseUrl: string;
  setApiBaseUrl: (url: string) => void;
  colors: typeof themeColors.dark;
};

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [isDarkMode, setIsDarkMode] = useState(true);
  const [geminiApiKey, setApiKey] = useState('');
  const [apiBaseUrl, setApiUrl] = useState('');

  useEffect(() => {
    const loadPreferences = async () => {
      try {
        const storedTheme = await AsyncStorage.getItem('@theme_preference');
        if (storedTheme !== null) {
          setIsDarkMode(storedTheme === 'dark');
        }
        const storedKey = await AsyncStorage.getItem('@gemini_api_key');
        if (storedKey) {
          setApiKey(storedKey);
        }
        const storedApiUrl = await AsyncStorage.getItem('@api_base_url');
        if (storedApiUrl) {
          setApiUrl(storedApiUrl);
        }
      } catch (e) {
        console.error('Failed to load preferences');
      }
    };
    loadPreferences();
  }, []);

  const toggleTheme = async (value: boolean) => {
    setIsDarkMode(value);
    try {
      await AsyncStorage.setItem('@theme_preference', value ? 'dark' : 'light');
    } catch (e) {
      console.error('Failed to save theme preference');
    }
  };

  const setGeminiApiKey = async (key: string) => {
    setApiKey(key);
    try {
      await AsyncStorage.setItem('@gemini_api_key', key);
    } catch (e) {
      console.error('Failed to save api key');
    }
  };

  const setApiBaseUrl = async (url: string) => {
    setApiUrl(url);
    try {
      await AsyncStorage.setItem('@api_base_url', url);
    } catch (e) {
      console.error('Failed to save api base url');
    }
  };

  return (
    <ThemeContext.Provider value={{
      isDarkMode,
      toggleTheme,
      geminiApiKey,
      setGeminiApiKey,
      apiBaseUrl,
      setApiBaseUrl,
      colors: isDarkMode ? themeColors.dark : themeColors.light
    }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (context === undefined) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return context;
}
