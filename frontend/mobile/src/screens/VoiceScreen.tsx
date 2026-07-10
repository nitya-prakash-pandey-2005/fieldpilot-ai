import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, ScrollView } from 'react-native';
import { Mic, Square, Volume2, ArrowLeft } from 'lucide-react-native';
import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system/legacy';
import config from '../config';
import { useTheme } from '../context/ThemeContext';

type VoiceState = 'IDLE' | 'RECORDING' | 'PROCESSING' | 'RESPONDING';

export function VoiceScreen() {
  const { colors, apiBaseUrl, geminiApiKey } = useTheme();
  const [state, setState] = useState<VoiceState>('IDLE');
  const [recording, setRecording] = useState<Audio.Recording | null>(null);
  
  // Data from backend
  const [transcript, setTranscript] = useState('');
  const [responseText, setResponseText] = useState('');
  const [evidence, setEvidence] = useState<any[]>([]);
  const [sound, setSound] = useState<Audio.Sound | null>(null);

  useEffect(() => {
    return () => {
      if (sound) sound.unloadAsync();
    };
  }, [sound]);

  const startRecording = async () => {
    try {
      console.log('Requesting permissions..');
      await Audio.requestPermissionsAsync();
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      console.log('Starting recording..');
      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      setRecording(recording);
      setState('RECORDING');
    } catch (err) {
      console.error('Failed to start recording', err);
    }
  };

  const stopRecording = async () => {
    if (!recording) return;
    
    setState('PROCESSING');
    await recording.stopAndUnloadAsync();
    const uri = recording.getURI();
    setRecording(null);

    // Send to backend
    if (uri) {
      sendToBackend(uri);
    } else {
      setState('IDLE');
    }
  };

  const sendToBackend = async (uri: string) => {
    try {
      const base64Audio = await FileSystem.readAsStringAsync(uri, {
        encoding: 'base64',
      });

      const apiUrl = apiBaseUrl || config.API_BASE_URL;
      const response = await fetch(`${apiUrl}/api/v1/voice/query_json`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Bypass-Tunnel-Reminder': 'true',
          'X-Gemini-API-Key': geminiApiKey || '',
        },
        body: JSON.stringify({
          audio_base64: base64Audio,
          project_id: 'P-001',
          zone_id: 'A12',
          worker_id: 'W-001'
        })
      });

      const text = await response.text();
      let data;
      try {
        data = JSON.parse(text);
      } catch (e) {
        throw new Error(text.substring(0, 50) || 'Invalid server response');
      }
      
      if (!response.ok) {
        throw new Error(data.detail || `Server error: ${response.status}`);
      }
      
      setTranscript(data.transcript || 'Unknown query');
      setResponseText(data.response_text || data.answer || 'No response from AI');
      setEvidence(data.evidence || []);
      
      setState('RESPONDING');
      
      // Play audio
      if (data.audio_base64) {
        playBase64Audio(data.audio_base64);
      }
      
    } catch (error) {
      console.error("Error sending voice query:", error);
      setState('IDLE');
    }
  };

  const playBase64Audio = async (base64Audio: string) => {
    try {
      const uri = `data:audio/mp3;base64,${base64Audio}`;
      const { sound } = await Audio.Sound.createAsync({ uri });
      setSound(sound);
      await sound.playAsync();
    } catch (e) {
      console.error("Error playing audio", e);
    }
  };

  const reset = () => {
    if (sound) sound.unloadAsync();
    setSound(null);
    setTranscript('');
    setResponseText('');
    setEvidence([]);
    setState('IDLE');
  };

  return (
    <View style={[styles.container, { backgroundColor: colors.bg }]}>
      {state === 'IDLE' && (
        <View style={styles.centerContent}>
          <TouchableOpacity 
            style={[styles.micButton, { backgroundColor: colors.surface }]}
            onPress={startRecording}
          >
            <Mic color={colors.primary} size={40} />
          </TouchableOpacity>
          <Text style={[styles.title, { color: colors.text }]}>Tap and speak in any language</Text>
          <Text style={[styles.subtitle, { color: colors.textSecondary }]}>Supports English, Hindi, Arabic, Tamil, Telugu + 95 more</Text>
        </View>
      )}

      {state === 'RECORDING' && (
        <View style={styles.centerContent}>
          <View style={[styles.micButton, { backgroundColor: colors.successSoft, borderColor: colors.success, borderWidth: 2 }]}>
            <Mic color={colors.success} size={40} />
          </View>
          <Text style={[styles.title, { color: colors.text }]}>Listening...</Text>
          
          <TouchableOpacity style={[styles.stopButton, { backgroundColor: colors.error }]} onPress={stopRecording}>
            <Square color="#fff" size={20} fill="#fff" />
            <Text style={styles.stopText}>Stop</Text>
          </TouchableOpacity>
        </View>
      )}

      {state === 'PROCESSING' && (
        <View style={styles.centerContent}>
          <ActivityIndicator size="large" color={colors.primary} style={{ transform: [{ scale: 1.5 }], marginBottom: 20 }} />
          <Text style={[styles.title, { color: colors.text }]}>Thinking...</Text>
        </View>
      )}

      {state === 'RESPONDING' && (
        <ScrollView style={styles.responseContainer} contentContainerStyle={{ paddingBottom: 40 }}>
          <View style={[styles.transcriptBox, { backgroundColor: colors.surface }]}>
            <Text style={[styles.transcriptLabel, { color: colors.textSecondary }]}>You said:</Text>
            <Text style={[styles.transcriptText, { color: colors.text }]}>"{transcript}"</Text>
          </View>

          <View style={[styles.responseBox, { backgroundColor: colors.primarySoft, borderColor: colors.primary }]}>
            <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 8 }}>
              <Volume2 color={colors.primary} size={24} style={{ marginRight: 8 }} />
              <Text style={[styles.responseLabel, { color: colors.primary }]}>Project Memory:</Text>
            </View>
            <Text style={[styles.responseText, { color: colors.text }]}>{responseText}</Text>
          </View>

          {evidence && evidence.length > 0 && (
            <View style={styles.evidenceSection}>
              <Text style={[styles.evidenceTitle, { color: colors.text }]}>Sources:</Text>
              {evidence.map((ev, i) => (
                <View key={i} style={[styles.evidenceCard, { backgroundColor: colors.surface, borderLeftColor: colors.success }]}>
                  <Text style={[styles.evSource, { color: colors.text }]}>{ev.source_id}</Text>
                  <Text style={[styles.evExcerpt, { color: colors.textSecondary }]}>"{ev.excerpt}"</Text>
                  <View style={styles.evFooter}>
                    <Text style={[styles.evMeta, { color: colors.textSecondary }]}>{ev.date}</Text>
                    {ev.approved_by && <Text style={[styles.evMeta, { color: colors.textSecondary }]}>• {ev.approved_by}</Text>}
                  </View>
                </View>
              ))}
            </View>
          )}

          <TouchableOpacity style={[styles.resetButton, { backgroundColor: colors.surfaceVariant }]} onPress={reset}>
            <ArrowLeft color={colors.text} size={20} />
            <Text style={[styles.resetText, { color: colors.text }]}>Ask another question</Text>
          </TouchableOpacity>
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#121212',
  },
  centerContent: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  micButton: {
    width: 100,
    height: 100,
    borderRadius: 50,
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 24,
  },
  micIdle: {
    backgroundColor: '#333',
  },
  micRecording: {
    backgroundColor: 'rgba(16, 185, 129, 0.2)',
    borderColor: '#10b981',
    borderWidth: 2,
  },
  title: {
    color: '#fff',
    fontSize: 20,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 8,
  },
  subtitle: {
    color: '#888',
    fontSize: 14,
    textAlign: 'center',
  },
  stopButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ef4444',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 24,
    marginTop: 40,
  },
  stopText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginLeft: 8,
  },
  responseContainer: {
    flex: 1,
    padding: 20,
  },
  transcriptBox: {
    backgroundColor: '#222',
    padding: 16,
    borderRadius: 12,
    marginBottom: 16,
  },
  transcriptLabel: {
    color: '#888',
    fontSize: 12,
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  transcriptText: {
    color: '#e2e8f0',
    fontSize: 16,
    fontStyle: 'italic',
  },
  responseBox: {
    backgroundColor: 'rgba(59, 130, 246, 0.1)',
    borderWidth: 1,
    borderColor: 'rgba(59, 130, 246, 0.3)',
    padding: 16,
    borderRadius: 12,
    marginBottom: 24,
  },
  responseLabel: {
    color: '#3b82f6',
    fontSize: 14,
    fontWeight: 'bold',
  },
  responseText: {
    color: '#fff',
    fontSize: 18,
    lineHeight: 26,
  },
  evidenceSection: {
    marginBottom: 24,
  },
  evidenceTitle: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginBottom: 12,
  },
  evidenceCard: {
    backgroundColor: '#1a1a1a',
    borderLeftWidth: 3,
    borderLeftColor: '#10b981',
    padding: 12,
    borderRadius: 8,
    marginBottom: 12,
  },
  evSource: {
    color: '#fff',
    fontWeight: 'bold',
    marginBottom: 4,
  },
  evExcerpt: {
    color: '#aaa',
    fontSize: 14,
    marginBottom: 8,
  },
  evFooter: {
    flexDirection: 'row',
    gap: 8,
  },
  evMeta: {
    color: '#666',
    fontSize: 12,
  },
  resetButton: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#333',
    padding: 16,
    borderRadius: 12,
    marginTop: 10,
  },
  resetText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: 'bold',
    marginLeft: 8,
  }
});
