import React, { useState, useEffect } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, TextInput, KeyboardAvoidingView, Platform, ScrollView, Alert } from 'react-native';
import { useTheme } from '../context/ThemeContext';
import { User, Settings, Shield, LogOut, Save, Wifi } from 'lucide-react-native';
import config from '../config';

// Real Settings section wired to ThemeContext's setApiBaseUrl/setGeminiApiKey
// — both were fully implemented (with AsyncStorage persistence) but no
// screen anywhere ever called them, so a real user had no way to point this
// app at a real backend (e.g. an ngrok/localtunnel URL for a phone during a
// live demo) or set an optional Gemini key override. AskAIScreen/VoiceScreen
// both read these values but the app had no UI to set them at all.
export function ProfileScreen() {
  const { colors, apiBaseUrl, setApiBaseUrl, geminiApiKey, setGeminiApiKey } = useTheme();
  const [urlInput, setUrlInput] = useState(apiBaseUrl);
  const [keyInput, setKeyInput] = useState(geminiApiKey);

  useEffect(() => { setUrlInput(apiBaseUrl); }, [apiBaseUrl]);
  useEffect(() => { setKeyInput(geminiApiKey); }, [geminiApiKey]);

  const handleSave = () => {
    setApiBaseUrl(urlInput.trim());
    setGeminiApiKey(keyInput.trim());
    Alert.alert('Saved', 'Settings updated.');
  };

  return (
    <KeyboardAvoidingView
      style={[styles.container, { backgroundColor: colors.bg }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView>
        <View style={[styles.header, { backgroundColor: colors.surface }]}>
          <View style={styles.avatarPlaceholder}>
            <User size={40} color={colors.cyan} />
          </View>
          <Text style={[styles.name, { color: colors.text }]}>Nitya Pandey</Text>
          <Text style={[styles.role, { color: colors.textSecondary }]}>Site Foreman • Zone A12</Text>
          <View style={[styles.badge, { backgroundColor: colors.success + '20' }]}>
            <Shield size={12} color={colors.success} style={{ marginRight: 4 }} />
            <Text style={[styles.badgeText, { color: colors.success }]}>AUTHORIZED</Text>
          </View>
        </View>

        <View style={styles.section}>
          <View style={styles.sectionTitleRow}>
            <Settings size={16} color={colors.textSecondary} />
            <Text style={[styles.sectionTitle, { color: colors.textSecondary }]}>Connection Settings</Text>
          </View>

          <Text style={[styles.label, { color: colors.textSecondary }]}>API Base URL</Text>
          <TextInput
            style={[styles.input, { backgroundColor: colors.surfaceVariant, color: colors.text, borderColor: colors.border }]}
            placeholder={config.API_BASE_URL}
            placeholderTextColor={colors.textSecondary}
            value={urlInput}
            onChangeText={setUrlInput}
            autoCapitalize="none"
            autoCorrect={false}
          />
          <Text style={[styles.hint, { color: colors.textSecondary }]}>
            Leave blank to use the default ({config.API_BASE_URL}). Set this to your tunnel/deployed backend URL (e.g. ngrok) when demoing on a real device.
          </Text>

          <Text style={[styles.label, { color: colors.textSecondary, marginTop: 20 }]}>Gemini API Key (optional)</Text>
          <TextInput
            style={[styles.input, { backgroundColor: colors.surfaceVariant, color: colors.text, borderColor: colors.border }]}
            placeholder="Only needed to override the server's own key"
            placeholderTextColor={colors.textSecondary}
            value={keyInput}
            onChangeText={setKeyInput}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
          />
          <Text style={[styles.hint, { color: colors.textSecondary }]}>
            The server already has its own LLM configured — this is only needed if you want Ask AI / Voice to use your personal key instead.
          </Text>

          <TouchableOpacity style={[styles.saveButton, { backgroundColor: colors.primary }]} onPress={handleSave}>
            <Save size={16} color="#fff" />
            <Text style={styles.saveButtonText}>Save Settings</Text>
          </TouchableOpacity>

          <View style={styles.statusRow}>
            <Wifi size={12} color={colors.textSecondary} />
            <Text style={[styles.statusText, { color: colors.textSecondary }]}>
              Currently using: {apiBaseUrl || config.API_BASE_URL}
            </Text>
          </View>
        </View>

        <View style={styles.menu}>
          <TouchableOpacity style={[styles.menuItem, { borderBottomColor: colors.border }]}>
            <Shield size={20} color={colors.text} />
            <Text style={[styles.menuText, { color: colors.text }]}>Privacy & Security</Text>
          </TouchableOpacity>

          <TouchableOpacity style={styles.menuItem}>
            <LogOut size={20} color={colors.error} />
            <Text style={[styles.menuText, { color: colors.error }]}>Log Out</Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  header: {
    padding: 40,
    paddingTop: 80,
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  avatarPlaceholder: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: 'rgba(0,212,255,0.1)',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 16,
    borderWidth: 2,
    borderColor: '#00D4FF',
  },
  name: {
    fontSize: 24,
    fontWeight: 'bold',
    marginBottom: 4,
  },
  role: {
    fontSize: 14,
    marginBottom: 12,
  },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 20,
  },
  badgeText: {
    fontSize: 10,
    fontWeight: 'bold',
    letterSpacing: 1,
  },
  section: {
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: 'rgba(255,255,255,0.1)',
  },
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    marginBottom: 16,
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: 'bold',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  label: {
    fontSize: 12,
    fontWeight: '600',
    marginBottom: 6,
  },
  input: {
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 14,
    minHeight: 44,
  },
  hint: {
    fontSize: 11,
    marginTop: 6,
    lineHeight: 15,
  },
  saveButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderRadius: 8,
    paddingVertical: 14,
    marginTop: 20,
    minHeight: 48,
  },
  saveButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: 'bold',
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginTop: 12,
    justifyContent: 'center',
  },
  statusText: {
    fontSize: 11,
  },
  menu: {
    padding: 20,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 16,
    borderBottomWidth: 1,
  },
  menuText: {
    fontSize: 16,
    marginLeft: 16,
    fontWeight: '500',
  }
});
