import React from 'react';
import { View, Text, Switch, StyleSheet, TextInput, KeyboardAvoidingView, ScrollView, Platform, TouchableOpacity, Alert } from 'react-native';
import { User, Moon, Sun, Key, Save, Server } from 'lucide-react-native';
import { useTheme } from '../context/ThemeContext';
import config from '../config';

export function ProfileScreen() {
  const { isDarkMode, toggleTheme, geminiApiKey, setGeminiApiKey, apiBaseUrl, setApiBaseUrl, colors } = useTheme();

  return (
    <KeyboardAvoidingView 
      style={{ flex: 1 }} 
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      enabled={Platform.OS === 'ios'}
    >
      <ScrollView 
        contentContainerStyle={[styles.container, { backgroundColor: colors.bg }]}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
      <View style={[styles.profileCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <View style={[styles.avatar, { backgroundColor: colors.primary }]}>
          <User color="#ffffff" size={40} />
        </View>
        <Text style={[styles.name, { color: colors.text }]}>Worker Profile</Text>
        <Text style={[styles.role, { color: colors.textSecondary }]}>Field Engineer</Text>
      </View>

      <View style={[styles.settingsCard, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>Appearance</Text>
        
        <View style={styles.settingRow}>
          <View style={styles.settingInfo}>
            {isDarkMode ? <Moon color={colors.text} size={24} /> : <Sun color={colors.text} size={24} />}
            <Text style={[styles.settingText, { color: colors.text }]}>Dark Mode</Text>
          </View>
          <Switch
            trackColor={{ false: '#767577', true: colors.primarySoft }}
            thumbColor={isDarkMode ? colors.primary : '#f4f3f4'}
            onValueChange={toggleTheme}
            value={isDarkMode}
          />
        </View>
      </View>
      
      <View style={[styles.settingsCard, { backgroundColor: colors.surface, borderColor: colors.border, marginTop: 16 }]}>
        <Text style={[styles.sectionTitle, { color: colors.text }]}>API Settings</Text>
        
        <View style={styles.settingInfo}>
          <Key color={colors.text} size={20} />
          <Text style={[styles.settingText, { color: colors.text }]}>Gemini API Key</Text>
        </View>
        
        <TextInput
          style={[styles.input, { 
            backgroundColor: colors.surfaceVariant, 
            color: colors.text, 
            borderColor: colors.border 
          }]}
          placeholder="Paste API Key here..."
          placeholderTextColor={colors.textSecondary}
          value={geminiApiKey}
          onChangeText={setGeminiApiKey}
          secureTextEntry={true}
        />
        <View style={styles.settingInfo}>
          <Server color={colors.text} size={20} />
          <Text style={[styles.settingText, { color: colors.text }]}>API Base URL</Text>
        </View>
        <TextInput
          style={[styles.input, { 
            backgroundColor: colors.surfaceVariant, 
            color: colors.text, 
            borderColor: colors.border,
            marginBottom: 16
          }]}
          placeholder={config.API_BASE_URL}
          placeholderTextColor={colors.textSecondary}
          value={apiBaseUrl}
          onChangeText={setApiBaseUrl}
          autoCapitalize="none"
          keyboardType="url"
        />

        <Text style={[styles.helpText, { color: colors.textSecondary }]}>
          Used for the Ask AI feature to answer project queries.
        </Text>
        <TouchableOpacity 
          style={[styles.saveButton, { backgroundColor: colors.primary }]}
          onPress={() => {
            Alert.alert('Success', 'API Key saved successfully!');
          }}
        >
          <Save color="#FFF" size={20} />
          <Text style={styles.saveButtonText}>Save Settings</Text>
        </TouchableOpacity>
      </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    padding: 20,
    paddingBottom: 60,
  },
  profileCard: {
    alignItems: 'center',
    padding: 30,
    borderRadius: 24,
    borderWidth: 1,
    marginBottom: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.1,
    shadowRadius: 12,
    elevation: 5,
  },
  avatar: {
    width: 80,
    height: 80,
    borderRadius: 40,
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
    borderRadius: 24,
    borderWidth: 1,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: 'bold',
    textTransform: 'uppercase',
    letterSpacing: 1,
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
    marginBottom: 12,
  },
  settingText: {
    fontSize: 16,
    fontWeight: '600',
  },
  input: {
    borderRadius: 12,
    paddingHorizontal: 16,
    paddingVertical: 12,
    fontSize: 16,
    borderWidth: 1,
    minHeight: 48,
    marginTop: 8,
  },
  helpText: {
    fontSize: 12,
    marginTop: 8,
  },
  saveButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 14,
    borderRadius: 12,
    marginTop: 20,
    gap: 8,
  },
  saveButtonText: {
    color: '#FFF',
    fontSize: 16,
    fontWeight: 'bold',
  }
});
