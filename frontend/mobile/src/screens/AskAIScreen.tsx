import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, KeyboardAvoidingView, Platform, ActivityIndicator } from 'react-native';
import { Send, FileText, CheckCircle2 } from 'lucide-react-native';
import config from '../config';
import { useTheme } from '../context/ThemeContext';

export function AskAIScreen() {
  const { colors, geminiApiKey, apiBaseUrl } = useTheme();
  const [query, setQuery] = useState('');
  const [messages, setMessages] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const handleSend = async () => {
    if (!query.trim()) return;
    
    const userMessage = { role: 'user', content: query };
    setMessages(prev => [...prev, userMessage]);
    setQuery('');
    setLoading(true);

    try {
      const baseUrl = apiBaseUrl || config.API_BASE_URL;
      const response = await fetch(`${baseUrl}/api/v1/memory/query`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'X-Gemini-API-Key': geminiApiKey,
          'Bypass-Tunnel-Reminder': 'true'
        },
        body: JSON.stringify({
          query: userMessage.content,
          project_id: "P-001",
          zone_id: "B3",
          worker_id: "W-022"
        })
      });
      
      const text = await response.text();
      let data;
      try {
        data = JSON.parse(text);
      } catch (e) {
        throw new Error(text.substring(0, 50));
      }
      
      if (!response.ok) {
        throw new Error(data.detail || `Server error: ${response.status}`);
      }
      
      setMessages(prev => [...prev, { role: 'ai', content: data }]);
    } catch (error: any) {
      console.error("AI Query Error", error);
      setMessages(prev => [...prev, { role: 'ai', content: { answer: `Error: ${error.message || 'Network error connecting to AI.'}`, evidence: [] } }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView 
      style={[styles.container, { backgroundColor: colors.bg }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      enabled={Platform.OS === 'ios'}
    >
      <ScrollView style={styles.chatContainer} contentContainerStyle={{ padding: 16 }}>
        {messages.map((msg, idx) => (
          <View key={idx} style={[
            styles.messageBubble, 
            msg.role === 'user' ? [styles.userBubble, { backgroundColor: colors.primary }] : [styles.aiBubble, { backgroundColor: colors.surface, borderColor: colors.border }]
          ]}>
            {msg.role === 'user' ? (
              <Text style={[styles.userText, { color: '#FFF' }]}>{msg.content}</Text>
            ) : (
              <View>
                <Text style={[styles.aiAnswer, { color: colors.text }]}>{msg.content.answer}</Text>
                
                {msg.content.evidence && msg.content.evidence.length > 0 && (
                  <View style={[styles.evidenceContainer, { borderTopColor: colors.border }]}>
                    <Text style={[styles.evidenceTitle, { color: colors.textSecondary }]}>Sources:</Text>
                    {msg.content.evidence.map((ev: any, eIdx: number) => (
                      <View key={eIdx} style={[styles.evidenceCard, { backgroundColor: colors.surfaceVariant, borderColor: colors.primarySoft }]}>
                        <View style={styles.evidenceHeader}>
                          <FileText size={14} color={colors.primary} />
                          <Text style={[styles.evidenceSource, { color: colors.primary }]}>{ev.source_type.replace('_', ' ')}</Text>
                          <Text style={[styles.evidenceDate, { color: colors.textSecondary }]}>{ev.date}</Text>
                        </View>
                        <Text style={[styles.evidenceExcerpt, { color: colors.text }]}>"{ev.excerpt}"</Text>
                        <View style={styles.evidenceFooter}>
                          <CheckCircle2 size={12} color={colors.success} />
                          <Text style={[styles.evidenceApprover, { color: colors.success }]}>Approved by {ev.approved_by}</Text>
                        </View>
                      </View>
                    ))}
                  </View>
                )}
              </View>
            )}
          </View>
        ))}
        {loading && (
          <View style={[styles.messageBubble, styles.aiBubble, { backgroundColor: colors.surface, borderColor: colors.border }]}>
            <ActivityIndicator color={colors.primary} />
          </View>
        )}
      </ScrollView>

      <View style={[styles.inputContainer, { backgroundColor: colors.surface, borderTopColor: colors.border }]}>
        <TextInput
          style={[styles.input, { 
            backgroundColor: colors.bg, 
            color: colors.text, 
            borderColor: colors.border 
          }]}
          placeholder={geminiApiKey ? "Ask Project Memory..." : "Please set API Key in Profile"}
          placeholderTextColor={colors.textSecondary}
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={handleSend}
          editable={!!geminiApiKey}
        />
        <TouchableOpacity 
          style={[styles.sendButton, { backgroundColor: geminiApiKey ? colors.primary : colors.surfaceVariant }]} 
          onPress={handleSend}
          disabled={!geminiApiKey}
        >
          <Send color={geminiApiKey ? "#fff" : colors.textSecondary} size={20} />
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0A0A0F',
  },
  chatContainer: {
    flex: 1,
  },
  messageBubble: {
    maxWidth: '88%',
    padding: 16,
    borderRadius: 12,
    marginBottom: 16,
  },
  userBubble: {
    backgroundColor: '#00D4FF',
    alignSelf: 'flex-end',
    borderBottomRightRadius: 2,
  },
  aiBubble: {
    backgroundColor: '#12121A',
    alignSelf: 'flex-start',
    borderBottomLeftRadius: 2,
    borderWidth: 1,
    borderColor: '#1E1E2E',
  },
  userText: {
    color: '#0A0A0F',
    fontSize: 16,
    fontWeight: '600'
  },
  aiAnswer: {
    color: '#FFF',
    fontSize: 16,
    lineHeight: 24,
  },
  evidenceContainer: {
    marginTop: 16,
    paddingTop: 12,
    borderTopWidth: 1,
    borderTopColor: '#1E1E2E',
  },
  evidenceTitle: {
    color: '#888',
    fontSize: 12,
    fontWeight: '800',
    marginBottom: 8,
    textTransform: 'uppercase',
    letterSpacing: 1
  },
  evidenceCard: {
    backgroundColor: '#0A0A0F',
    padding: 12,
    borderRadius: 8,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: '#7B61FF40',
  },
  evidenceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  evidenceSource: {
    color: '#7B61FF',
    fontSize: 13,
    fontWeight: 'bold',
    marginLeft: 6,
    flex: 1,
    textTransform: 'capitalize',
  },
  evidenceDate: {
    color: '#888',
    fontSize: 12,
  },
  evidenceExcerpt: {
    color: '#DDD',
    fontSize: 14,
    fontStyle: 'italic',
    marginBottom: 10,
    lineHeight: 20
  },
  evidenceFooter: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  evidenceApprover: {
    color: '#00C851',
    fontSize: 12,
    marginLeft: 6,
    fontWeight: '600'
  },
  inputContainer: {
    flexDirection: 'row',
    padding: 16,
    backgroundColor: '#12121A',
    borderTopWidth: 1,
    borderTopColor: '#1E1E2E',
    alignItems: 'center'
  },
  input: {
    flex: 1,
    backgroundColor: '#0A0A0F',
    color: '#FFF',
    borderRadius: 24,
    paddingHorizontal: 20,
    paddingVertical: 14,
    marginRight: 12,
    fontSize: 16,
    borderWidth: 1,
    borderColor: '#1E1E2E',
    minHeight: 48
  },
  sendButton: {
    width: 48,
    height: 48,
    backgroundColor: '#7B61FF',
    borderRadius: 24,
    justifyContent: 'center',
    alignItems: 'center',
  }
});
