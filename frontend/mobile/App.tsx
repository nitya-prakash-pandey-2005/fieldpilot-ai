import React, { useEffect, useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View, Text } from 'react-native';
import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { TabNavigator } from './src/navigation/TabNavigator';
import config from './src/config';

export default function App() {
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
    <SafeAreaProvider>
      <SafeAreaView style={styles.container} edges={['top']}>
        {/* Connection Status Header */}
        <View style={styles.header}>
          <Text style={styles.headerTitle}>ASK THE WALL</Text>
          <View style={styles.healthBadge}>
            <View style={[styles.healthDot, { backgroundColor: isHealthy ? '#22c55e' : isHealthy === false ? '#ef4444' : '#64748b' }]} />
            <Text style={styles.healthText}>{isHealthy ? 'Online' : 'Offline'}</Text>
          </View>
        </View>

        <NavigationContainer theme={DarkTheme}>
          <TabNavigator />
        </NavigationContainer>
        <StatusBar style="light" />
      </SafeAreaView>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#1e1e1e',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: '#1e1e1e',
    borderBottomWidth: 1,
    borderBottomColor: '#333',
  },
  headerTitle: {
    color: '#fff',
    fontSize: 18,
    fontWeight: 'bold',
    letterSpacing: 1,
  },
  healthBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#2a2a2a',
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#333',
  },
  healthDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginRight: 6,
  },
  healthText: {
    color: '#aaa',
    fontSize: 10,
    fontWeight: 'bold',
  }
});
