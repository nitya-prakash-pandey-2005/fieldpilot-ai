import React, { useState, useRef, useEffect } from 'react';
import { Mic, Loader, Search, Volume2, X } from 'lucide-react';

export default function VoiceSearchBar() {
  const [state, setState] = useState<'IDLE' | 'RECORDING' | 'PROCESSING' | 'RESPONDING'>('IDLE');
  const [transcript, setTranscript] = useState('');
  const [responseText, setResponseText] = useState('');
  
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);

  // Initialize Speech Recognition for immediate UI feedback
  const recognitionRef = useRef<any>(null);

  useEffect(() => {
    // @ts-ignore - Web Speech API
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      recognitionRef.current = new SpeechRecognition();
      recognitionRef.current.continuous = true;
      recognitionRef.current.interimResults = true;
      recognitionRef.current.lang = 'en-US';

      recognitionRef.current.onresult = (event: any) => {
        let interimTranscript = '';
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          interimTranscript += event.results[i][0].transcript;
        }
        setTranscript(interimTranscript);
      };
    }
  }, []);

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorderRef.current = new MediaRecorder(stream);
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      mediaRecorderRef.current.onstop = async () => {
        const audioBlob = new Blob(audioChunksRef.current, { type: 'audio/webm' });
        await sendAudioToBackend(audioBlob);
      };

      mediaRecorderRef.current.start();
      if (recognitionRef.current) recognitionRef.current.start();
      setState('RECORDING');
    } catch (err) {
      console.error("Microphone access denied", err);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && state === 'RECORDING') {
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      if (recognitionRef.current) recognitionRef.current.stop();
      setState('PROCESSING');
    }
  };

  const sendAudioToBackend = async (blob: Blob) => {
    try {
      const formData = new FormData();
      formData.append('audio', blob, 'voice_query.webm');
      formData.append('project_id', 'P-001');
      formData.append('zone_id', 'A12'); // Mock for dashboard context
      formData.append('worker_id', 'Admin-01');

      const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const res = await fetch(`${apiUrl}/api/v1/voice/query`, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      setResponseText(data.response_text);
      if (data.transcript) {
          setTranscript(data.transcript); // Replace with backend truth
      }
      setState('RESPONDING');

      if (data.audio_base64) {
        playTTS(data.audio_base64);
      }
    } catch (err) {
      console.error("Backend voice query failed", err);
      setState('IDLE');
    }
  };

  const playTTS = async (base64String: string) => {
    try {
      if (!audioContextRef.current) {
        audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
      }
      const audioCtx = audioContextRef.current;
      
      // Decode base64
      const binaryString = window.atob(base64String);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
          bytes[i] = binaryString.charCodeAt(i);
      }
      
      const audioBuffer = await audioCtx.decodeAudioData(bytes.buffer);
      const source = audioCtx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(audioCtx.destination);
      source.start();
    } catch (e) {
      console.error("Error playing TTS", e);
    }
  };

  const reset = () => {
    setState('IDLE');
    setTranscript('');
    setResponseText('');
  };

  return (
    <div className="relative">
      <div 
        className={`flex items-center bg-atw-surface/60 border rounded-full px-4 py-2 w-96 transition-all duration-300 ${
          state === 'RECORDING' ? 'border-atw-cyan shadow-[0_0_15px_rgba(34,211,238,0.3)]' : 'border-white/10 hover:border-white/30'
        }`}
      >
        {state === 'IDLE' && (
          <button onClick={startRecording} className="text-white/50 hover:text-atw-cyan transition-colors mr-3 focus:outline-none">
            <Mic size={18} />
          </button>
        )}
        
        {state === 'RECORDING' && (
          <button onClick={stopRecording} className="text-atw-cyan mr-3 animate-pulse focus:outline-none flex gap-1">
             <div className="w-1 h-4 bg-atw-cyan rounded-full animate-pulse" style={{animationDelay: '0ms'}}></div>
             <div className="w-1 h-4 bg-atw-cyan rounded-full animate-pulse" style={{animationDelay: '100ms'}}></div>
             <div className="w-1 h-4 bg-atw-cyan rounded-full animate-pulse" style={{animationDelay: '200ms'}}></div>
          </button>
        )}

        {state === 'PROCESSING' && (
          <Loader size={18} className="text-atw-purple mr-3 animate-spin" />
        )}

        {state === 'RESPONDING' && (
          <Volume2 size={18} className="text-atw-cyan mr-3 animate-pulse" />
        )}

        <input 
          type="text" 
          value={transcript}
          onChange={(e) => setTranscript(e.target.value)}
          placeholder={state === 'IDLE' ? "FieldPilot AI... (Tap mic or type)" : "Listening..."}
          className="bg-transparent border-none outline-none text-white w-full text-sm placeholder-white/30"
          readOnly={state === 'RECORDING' || state === 'PROCESSING'}
        />
        
        {state === 'IDLE' ? (
          <Search size={16} className="text-white/30 ml-2" />
        ) : (
          <button onClick={reset} className="text-white/50 hover:text-white ml-2">
            <X size={16} />
          </button>
        )}
      </div>

      {/* Floating Response Popover */}
      {state === 'RESPONDING' && responseText && (
        <div className="absolute top-12 left-0 w-[400px] bg-atw-surface/95 backdrop-blur-xl border border-atw-cyan/30 rounded-xl p-5 shadow-2xl z-50 animate-in fade-in slide-in-from-top-4">
          <div className="flex items-center gap-2 mb-3">
             <div className="w-6 h-6 rounded bg-atw-cyan/20 flex items-center justify-center">
                <Volume2 size={14} className="text-atw-cyan" />
             </div>
             <span className="text-atw-cyan font-semibold text-sm tracking-wide">AI Project Memory</span>
          </div>
          <p className="text-white/90 leading-relaxed text-sm">{responseText}</p>
        </div>
      )}
    </div>
  );
}
