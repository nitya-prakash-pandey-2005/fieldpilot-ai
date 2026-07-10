import React, { useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View, Text } from 'react-native';
import { NavigationContainer, DarkTheme, DefaultTheme } from '@react-navigation/native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { TabNavigator } from './src/navigation/TabNavigator';
import config from './src/config';
import { ThemeProvider, useTheme } from './src/context/ThemeContext';

function AppContent() {
  const { isDarkMode, colors } = useTheme();
  const [isHealthy, setIsHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch(`${config.API_BASE_URL}/api/v1/health`);
        const data = await res.json();
        setIsHealthy(data.status === 'ok');
      } catch (e) {
        setIsHealthy(false);
      }
    };
    checkHealth();
    // Poll every 10 seconds for hackathon robustness
    const interval = setInterval(checkHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <SafeAreaView style={[styles.container, { backgroundColor: colors.bg }]} edges={['top']}>
      {/* Connection Status Header */}
      <View style={[styles.header, { backgroundColor: colors.surface, borderBottomColor: colors.border }]}>
        <Text style={[styles.headerTitle, { color: colors.text }]}>FIELDPILOT AI</Text>
        <View style={[styles.healthBadge, { backgroundColor: colors.surfaceVariant, borderColor: colors.border }]}>
          <View style={[styles.healthDot, { backgroundColor: isHealthy ? colors.success : isHealthy === false ? colors.error : colors.textSecondary }]} />
          <Text style={[styles.healthText, { color: colors.textSecondary }]}>{isHealthy ? 'Online' : 'Offline'}</Text>
        </View>
      </View>

      <NavigationContainer theme={isDarkMode ? DarkTheme : DefaultTheme}>
        <TabNavigator />
      </NavigationContainer>
      <StatusBar style={isDarkMode ? "light" : "dark"} />
    </SafeAreaView>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <ThemeProvider>
        <AppContent />
      </ThemeProvider>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    letterSpacing: 1,
  },
  healthBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    borderWidth: 1,
  },
  healthDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  healthText: {
    fontSize: 10,
    fontWeight: 'bold',
  }
});
