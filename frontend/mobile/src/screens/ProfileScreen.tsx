import React, { useState, useEffect } from 'react';
import { View, Text, Switch, StyleSheet } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { User, Moon, Sun } from 'lucide-react-native';

export function ProfileScreen() {
  const [isDarkMode, setIsDarkMode] = useState(true);

  useEffect(() => {
    loadThemePreference();
  }, []);

  const loadThemePreference = async () => {
    try {
      const storedTheme = await AsyncStorage.getItem('@theme_preference');
      if (storedTheme !== null) {
        setIsDarkMode(storedTheme === 'dark');
      }
    } catch (e) {
      console.error('Failed to load theme preference');
    }
  };

  const toggleSwitch = async (value: boolean) => {
    setIsDarkMode(value);
    try {
      await AsyncStorage.setItem('@theme_preference', value ? 'dark' : 'light');
    } catch (e) {
      console.error('Failed to save theme preference');
    }
  };

  const themeColors = isDarkMode ? {
    bg: '#121212',
    surface: '#1e1e1e',
    text: '#ffffff',
    textSecondary: '#a0a0a0',
    border: '#333333'
  } : {
    bg: '#f0f4ff',
    surface: '#ffffff',
    text: '#0a0a1a',
    textSecondary: '#4a5568',
    border: '#e2e8f0'
  };

  return (
    <View style={[styles.container, { backgroundColor: themeColors.bg }]}>
      <View style={[styles.profileCard, { backgroundColor: themeColors.surface, borderColor: themeColors.border }]}>
        <View style={styles.avatar}>
          <User color="#ffffff" size={40} />
        </View>
        <Text style={[styles.name, { color: themeColors.text }]}>Worker Profile</Text>
        <Text style={[styles.role, { color: themeColors.textSecondary }]}>Field Engineer</Text>
      </View>

      <View style={[styles.settingsCard, { backgroundColor: themeColors.surface, borderColor: themeColors.border }]}>
        <Text style={[styles.sectionTitle, { color: themeColors.text }]}>Settings</Text>
        
        <View style={styles.settingRow}>
          <View style={styles.settingInfo}>
            {isDarkMode ? <Moon color={themeColors.text} size={24} /> : <Sun color={themeColors.text} size={24} />}
            <Text style={[styles.settingText, { color: themeColors.text }]}>Dark Mode</Text>
          </View>
          <Switch
            trackColor={{ false: '#767577', true: '#3b82f6' }}
            thumbColor={isDarkMode ? '#ffffff' : '#f4f3f4'}
            onValueChange={toggleSwitch}
            value={isDarkMode}
          />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 20,
  },
  profileCard: {
    alignItems: 'center',
    padding: 30,
    borderRadius: 16,
    borderWidth: 1,
    marginBottom: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 8,
    elevation: 3,
  },
  avatar: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#3b82f6',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
  },
  name: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  role: {
    fontSize: 16,
  },
  settingsCard: {
    padding: 20,
    borderRadius: 16,
    borderWidth: 1,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: 'bold',
    marginBottom: 20,
  },
  settingRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  settingInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  settingText: {
    fontSize: 16,
    fontWeight: '500',
  }
});
