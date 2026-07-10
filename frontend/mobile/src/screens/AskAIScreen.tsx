import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, ScrollView, StyleSheet, KeyboardAvoidingView, Platform, ActivityIndicator } from 'react-native';
import { Send, FileText, CheckCircle2 } from 'lucide-react-native';
import config from '../config';

export function AskAIScreen() {
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
      const response = await fetch(`${config.API_BASE_URL}/api/v1/memory/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: userMessage.content,
          project_id: "P-001",
          zone_id: "B3",
          worker_id: "W-022"
        })
      });
      
      const data = await response.json();
      setMessages(prev => [...prev, { role: 'ai', content: data }]);
    } catch (error) {
      console.error("AI Query Error", error);
      setMessages(prev => [...prev, { role: 'ai', content: { answer: "Network error connecting to AI.", evidence: [] } }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView 
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={90}
    >
      <ScrollView style={styles.chatContainer} contentContainerStyle={{ padding: 16 }}>
        {messages.map((msg, idx) => (
          <View key={idx} style={[styles.messageBubble, msg.role === 'user' ? styles.userBubble : styles.aiBubble]}>
            {msg.role === 'user' ? (
              <Text style={styles.userText}>{msg.content}</Text>
            ) : (
              <View>
                <Text style={styles.aiAnswer}>{msg.content.answer}</Text>
                
                {msg.content.evidence && msg.content.evidence.length > 0 && (
                  <View style={styles.evidenceContainer}>
                    <Text style={styles.evidenceTitle}>Sources:</Text>
                    {msg.content.evidence.map((ev: any, eIdx: number) => (
                      <View key={eIdx} style={styles.evidenceCard}>
                        <View style={styles.evidenceHeader}>
                          <FileText size={14} color="#a855f7" />
                          <Text style={styles.evidenceSource}>{ev.source_type.replace('_', ' ')}</Text>
                          <Text style={styles.evidenceDate}>{ev.date}</Text>
                        </View>
                        <Text style={styles.evidenceExcerpt}>"{ev.excerpt}"</Text>
                        <View style={styles.evidenceFooter}>
                          <CheckCircle2 size={12} color="#22c55e" />
                          <Text style={styles.evidenceApprover}>Approved by {ev.approved_by}</Text>
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
          <View style={[styles.messageBubble, styles.aiBubble]}>
            <ActivityIndicator color="#a855f7" />
          </View>
        )}
      </ScrollView>

      <View style={styles.inputContainer}>
        <TextInput
          style={styles.input}
          placeholder="Ask Project Memory..."
          placeholderTextColor="#666"
          value={query}
          onChangeText={setQuery}
          onSubmitEditing={handleSend}
        />
        <TouchableOpacity style={styles.sendButton} onPress={handleSend}>
          <Send color="#fff" size={20} />
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
