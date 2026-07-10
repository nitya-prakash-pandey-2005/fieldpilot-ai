import React, { useState, useEffect } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, ScrollView } from 'react-native';
import { Mic, Square, Volume2, ArrowLeft } from 'lucide-react-native';
import { Audio } from 'expo-av';

type VoiceState = 'IDLE' | 'RECORDING' | 'PROCESSING' | 'RESPONDING';

export function VoiceScreen() {
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
      const formData = new FormData();
      formData.append('audio', {
        uri,
        type: 'audio/m4a',
        name: 'voice_query.m4a'
      } as any);
      formData.append('project_id', 'P-001');
      formData.append('zone_id', 'A12');
      formData.append('worker_id', 'W-001');

      // Note: Use your actual local IP address or tunnel URL for production
      const apiUrl = process.env.EXPO_PUBLIC_API_URL || 'http://127.0.0.1:8000';
      const response = await fetch(`${apiUrl}/api/v1/voice/query`, {
        method: 'POST',
        body: formData,
        headers: {
          'Accept': 'application/json',
        },
      });

      const data = await response.json();
      
      setTranscript(data.transcript);
      setResponseText(data.response_text);
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
    <View style={styles.container}>
      {state === 'IDLE' && (
        <View style={styles.centerContent}>
          <TouchableOpacity 
            style={[styles.micButton, styles.micIdle]}
            onPress={startRecording}
          >
            <Mic color="#fff" size={40} />
          </TouchableOpacity>
          <Text style={styles.title}>Tap and speak in any language</Text>
          <Text style={styles.subtitle}>Supports English, Hindi, Arabic, Tamil, Telugu + 95 more</Text>
        </View>
      )}

      {state === 'RECORDING' && (
        <View style={styles.centerContent}>
          <View style={[styles.micButton, styles.micRecording]}>
            <Mic color="#10b981" size={40} />
          </View>
          <Text style={styles.title}>Listening...</Text>
          
          <TouchableOpacity style={styles.stopButton} onPress={stopRecording}>
            <Square color="#fff" size={20} fill="#fff" />
            <Text style={styles.stopText}>Stop</Text>
          </TouchableOpacity>
        </View>
      )}

      {state === 'PROCESSING' && (
        <View style={styles.centerContent}>
          <ActivityIndicator size="large" color="#3b82f6" style={{ transform: [{ scale: 1.5 }], marginBottom: 20 }} />
          <Text style={styles.title}>Thinking...</Text>
        </View>
      )}

      {state === 'RESPONDING' && (
        <ScrollView style={styles.responseContainer} contentContainerStyle={{ paddingBottom: 40 }}>
          <View style={styles.transcriptBox}>
            <Text style={styles.transcriptLabel}>You said:</Text>
            <Text style={styles.transcriptText}>"{transcript}"</Text>
          </View>

          <View style={styles.responseBox}>
            <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 8 }}>
              <Volume2 color="#3b82f6" size={24} style={{ marginRight: 8 }} />
              <Text style={styles.responseLabel}>Project Memory:</Text>
            </View>
            <Text style={styles.responseText}>{responseText}</Text>
          </View>

          {evidence && evidence.length > 0 && (
            <View style={styles.evidenceSection}>
              <Text style={styles.evidenceTitle}>Sources:</Text>
              {evidence.map((ev, i) => (
                <View key={i} style={styles.evidenceCard}>
                  <Text style={styles.evSource}>{ev.source_id}</Text>
                  <Text style={styles.evExcerpt}>"{ev.excerpt}"</Text>
                  <View style={styles.evFooter}>
                    <Text style={styles.evMeta}>{ev.date}</Text>
                    {ev.approved_by && <Text style={styles.evMeta}>• {ev.approved_by}</Text>}
                  </View>
                </View>
              ))}
            </View>
          )}

          <TouchableOpacity style={styles.resetButton} onPress={reset}>
            <ArrowLeft color="#fff" size={20} />
            <Text style={styles.resetText}>Ask another question</Text>
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
