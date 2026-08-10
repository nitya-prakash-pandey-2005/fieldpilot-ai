"use client";

/**
 * Worker View — the phone, standing in for the glasses.
 *
 * Camera, microphone and speaker on one device, doing the two jobs the pitch
 * promises: watching for danger without being asked, and answering when asked.
 *
 * TWO LOOPS, DELIBERATELY SEPARATE
 *
 *   Safety   every WATCH_INTERVAL_MS, a downscaled frame goes to /worker/watch,
 *            which runs the on-device ONNX detector (~0.7s). The server speaks
 *            only when the hazard picture CHANGES, so standing next to the same
 *            open edge does not produce an alert every three seconds.
 *
 *   Question on demand only. Hold the button, talk, release. Audio plus the
 *            current frame go to /worker/ask, which transcribes, routes by
 *            intent, and speaks the answer back.
 *
 * WHY HOLD-TO-TALK AND NOT ALWAYS-ON. A wake word needs continuous recognition,
 * which on the web means the Web Speech API — Chrome-only, streams audio to
 * Google, and drops its session every minute or so. Hold-to-talk works in every
 * browser, costs no battery when idle, and cannot mishear a passing conversation
 * as a command. The hands-free toggle below enables the wake word where the
 * browser supports it, and says so where it does not.
 *
 * TWO BROWSER CONSTRAINTS THAT WILL BITE, HANDLED HERE
 *
 *   Secure context. getUserMedia is refused on plain http:// from anything but
 *   localhost, so opening this at http://<laptop-ip>:3000 on a phone gives no
 *   camera and no microphone. The page detects that and says exactly what to do
 *   instead of showing a dead preview.
 *
 *   Autoplay. Audio cannot start without a user gesture, so the first tap on
 *   "Go on shift" primes a silent buffer. Without it the worker gets hazard
 *   alerts they never hear — the worst possible failure for a safety feature,
 *   because silence is indistinguishable from "all clear".
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { apiBase } from '@/lib/api';
import {
  AlertTriangle, Camera, Loader2, Mic, Radio, ShieldCheck, Volume2, WifiOff,
} from 'lucide-react';

const WATCH_INTERVAL_MS = 3000;
const WATCH_FRAME_W = 640;      // the detector letterboxes to 640 anyway

type Entry = {
  id: number;
  who: 'worker' | 'system';
  text: string;
  meta?: string;
  tone?: 'normal' | 'hazard' | 'warn';
};

export default function WorkerPage() {
  const API = apiBase();

  const [onShift, setOnShift] = useState(false);
  const [secure, setSecure] = useState(true);
  const [camError, setCamError] = useState<string | null>(null);
  const [zone, setZone] = useState('A12');
  const [workerId, setWorkerId] = useState('W-001');
  const [mode, setMode] = useState<'cloud' | 'edge'>('cloud');

  const [listening, setListening] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [hazards, setHazards] = useState<any[]>([]);
  const [watchInfo, setWatchInfo] = useState<{ ms: number; backend: string } | null>(null);
  const [online, setOnline] = useState(true);
  const [log, setLog] = useState<Entry[]>([]);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const watchTimer = useRef<any>(null);
  const busyRef = useRef(false);          // don't stack watch calls
  const nextId = useRef(1);

  const say = useCallback((e: Omit<Entry, 'id'>) => {
    setLog(prev => [{ ...e, id: nextId.current++ }, ...prev].slice(0, 40));
  }, []);

  // -- secure-context check ------------------------------------------------

  useEffect(() => {
    setSecure(typeof window !== 'undefined' && window.isSecureContext);
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    setOnline(navigator.onLine);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off); };
  }, []);

  // -- audio ---------------------------------------------------------------

  const playAudio = useCallback((b64: string) => {
    if (!audioRef.current) return;
    audioRef.current.src = `data:audio/wav;base64,${b64}`;
    audioRef.current.play().catch(() => {
      say({ who: 'system', text: 'Audio is blocked by the browser. Tap anywhere, then ask again.', tone: 'warn' });
    });
  }, [say]);

  const primeAudio = () => {
    // A one-sample silent WAV played inside the tap that starts the shift. This
    // is what buys the right to autoplay hazard alerts later.
    const el = audioRef.current;
    if (!el) return;
    el.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA=';
    el.play().catch(() => {});
  };

  // -- camera --------------------------------------------------------------

  const goOnShift = useCallback(async () => {
    primeAudio();
    setCamError(null);
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1280 } },
        audio: true,
      });
      streamRef.current = s;
      if (videoRef.current) { videoRef.current.srcObject = s; await videoRef.current.play(); }
      setOnShift(true);
      say({ who: 'system', text: `On shift in zone ${zone}. Watching for hazards.` });
    } catch (e: any) {
      setCamError(
        window.isSecureContext
          ? `${e?.name ?? 'Error'}: ${e?.message ?? e}`
          : 'Camera and microphone need an HTTPS page. See the banner above.',
      );
    }
  }, [zone, say]);

  const goOffShift = useCallback(() => {
    clearInterval(watchTimer.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
    streamRef.current = null;
    setOnShift(false);
    setHazards([]);
    say({ who: 'system', text: 'Off shift. Hazard watch stopped.' });
  }, [say]);

  useEffect(() => () => {
    clearInterval(watchTimer.current);
    streamRef.current?.getTracks().forEach(t => t.stop());
  }, []);

  const grabFrame = useCallback((maxW = WATCH_FRAME_W): string | null => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return null;
    const scale = Math.min(1, maxW / v.videoWidth);
    const c = document.createElement('canvas');
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext('2d')!.drawImage(v, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.7).split(',')[1];
  }, []);

  // -- the safety loop -----------------------------------------------------

  useEffect(() => {
    if (!onShift) return;
    watchTimer.current = setInterval(async () => {
      // Skip rather than queue. A phone on a slow link would otherwise build a
      // backlog and start reporting hazards from a minute ago.
      if (busyRef.current || thinking) return;
      const frame = grabFrame();
      if (!frame) return;

      busyRef.current = true;
      try {
        const res = await fetch(`${API}/api/v1/worker/watch`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ frame_b64: frame, worker_id: workerId, zone_id: zone, mode: 'edge' }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const out = await res.json();

        if (out.status === 'unavailable') {
          setWatchInfo({ ms: 0, backend: out.reason ?? 'detector unavailable' });
          return;
        }
        setHazards(out.hazards ?? []);
        setWatchInfo({ ms: out.latency_ms, backend: out.backend });

        if (out.speak && out.spoken_text) {
          say({ who: 'system', text: out.spoken_text, tone: 'hazard', meta: out.backend });
          if (out.audio_base64) playAudio(out.audio_base64);
        }
      } catch {
        setWatchInfo(null);
      } finally {
        busyRef.current = false;
      }
    }, WATCH_INTERVAL_MS);

    return () => clearInterval(watchTimer.current);
  }, [onShift, thinking, API, workerId, zone, grabFrame, playAudio, say]);

  // -- the question loop ---------------------------------------------------

  const startListening = useCallback(async () => {
    const s = streamRef.current;
    if (!s) return;
    chunksRef.current = [];
    const rec = new MediaRecorder(s, { mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : '' });
    rec.ondataavailable = e => { if (e.data.size) chunksRef.current.push(e.data); };
    rec.onstop = async () => {
      const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
      if (blob.size < 1200) {
        say({ who: 'system', text: 'That was too short to hear. Hold the button while you speak.', tone: 'warn' });
        return;
      }
      const reader = new FileReader();
      reader.onload = () => askWith(String(reader.result).split(',')[1]);
      reader.readAsDataURL(blob);
    };
    recorderRef.current = rec;
    rec.start();
    setListening(true);
  }, [say]);

  const stopListening = useCallback(() => {
    recorderRef.current?.stop();
    setListening(false);
  }, []);

  const askWith = useCallback(async (audio_b64: string) => {
    setThinking(true);
    try {
      const res = await fetch(`${API}/api/v1/worker/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audio_b64, audio_filename: 'audio.webm',
          frame_b64: grabFrame(1280), worker_id: workerId, zone_id: zone, mode,
        }),
      });
      const out = await res.json();

      if (out.status === 'no_speech' || out.status === 'stt_failed') {
        say({ who: 'system', text: out.answer ?? `Could not transcribe: ${out.error}`, tone: 'warn' });
        return;
      }
      say({ who: 'worker', text: out.transcript, meta: out.stt_backend });
      say({
        who: 'system', text: out.answer,
        meta: `${out.intent} · ${(out.latency_ms / 1000).toFixed(1)}s`
              + (out.citations?.length ? ` · ${out.citations[0].source}` : '')
              + (out.spoken_ok ? '' : ' · NOT SPOKEN'),
        tone: out.compliance?.verdict === 'FAIL' ? 'hazard' : 'normal',
      });
      if (out.audio_base64) playAudio(out.audio_base64);
    } catch (e: any) {
      say({ who: 'system', text: `Could not reach the site server: ${e?.message ?? e}`, tone: 'warn' });
    } finally {
      setThinking(false);
    }
  }, [API, grabFrame, workerId, zone, mode, playAudio, say]);

  // -- render --------------------------------------------------------------

  const hazardActive = hazards.length > 0;

  return (
    <div className="min-h-screen w-full bg-[var(--bg-base)] text-[var(--text-primary)] flex flex-col">
      <audio ref={audioRef} className="hidden" />

      {/* header */}
      <header className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between gap-3 sticky top-0 z-20 bg-[var(--bg-surface)]">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold tracking-tight">FieldPilot</span>
            <span className="text-[9px] font-bold tracking-wider px-1.5 py-0.5 rounded"
                  style={{ color: '#000', background: 'var(--amber)' }}>
              PHONE AS GLASSES
            </span>
          </div>
          <div className="text-[10px] text-[var(--text-muted)] mt-0.5 flex items-center gap-2">
            {online ? <Radio size={10} className="text-[var(--pass)]" /> : <WifiOff size={10} className="text-[var(--fail)]" />}
            {online ? 'connected' : 'offline'}
            {watchInfo && <span>· watch {watchInfo.ms}ms</span>}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <select value={zone} onChange={e => setZone(e.target.value)}
                  className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded px-2 py-1 text-xs">
            {['A12', 'B3', 'C7', 'D4'].map(z => <option key={z} value={z}>Zone {z}</option>)}
          </select>
          <select value={mode} onChange={e => setMode(e.target.value as any)}
                  className="bg-[var(--bg-elevated)] border border-[var(--border-subtle)] rounded px-2 py-1 text-xs">
            <option value="cloud">Cloud</option>
            <option value="edge">Offline</option>
          </select>
        </div>
      </header>

      {/* insecure-context warning */}
      {!secure && (
        <div className="px-4 py-3 text-xs" style={{ background: 'color-mix(in srgb, var(--fail) 14%, transparent)' }}>
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="text-[var(--fail)] mt-0.5 shrink-0" />
            <div>
              <strong className="text-[var(--fail)]">Camera and microphone are blocked on this address.</strong>
              <p className="text-[var(--text-secondary)] mt-1">
                Browsers only grant them on an HTTPS page (or localhost). Open the HTTPS tunnel
                URL on this phone instead — the same page will then have full camera, microphone
                and speaker access.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* camera */}
      <div className="relative bg-black" style={{ aspectRatio: '3 / 4', maxHeight: '52vh' }}>
        <video ref={videoRef} muted playsInline className="w-full h-full object-cover" />

        {!onShift && (
          <div className="absolute inset-0 grid place-items-center bg-black/70 px-6 text-center">
            <div>
              <Camera size={30} className="mx-auto text-[var(--text-muted)] mb-3" />
              <p className="text-sm text-[var(--text-secondary)] mb-4">
                The camera is your eyes, the speaker is your ear. Nothing is recorded until you go on shift.
              </p>
              <button onClick={goOnShift}
                      className="px-6 py-3 rounded-xl font-semibold text-black bg-[var(--cyan)] active:scale-95 transition-transform">
                Go on shift
              </button>
              {camError && <p className="text-xs text-[var(--fail)] mt-3">{camError}</p>}
            </div>
          </div>
        )}

        {/* hazard overlay */}
        {onShift && hazardActive && (
          <div className="absolute inset-0 pointer-events-none border-4 animate-pulse motion-reduce:animate-none"
               style={{ borderColor: 'var(--fail)' }} />
        )}

        {onShift && (
          <div className="absolute top-2 left-2 right-2 flex items-center justify-between gap-2">
            <span className="text-[10px] font-bold px-2 py-1 rounded flex items-center gap-1.5"
                  style={{ background: hazardActive ? 'var(--fail)' : 'rgba(0,0,0,0.6)', color: '#fff' }}>
              {hazardActive
                ? <><AlertTriangle size={11} /> {hazards.length} HAZARD{hazards.length > 1 ? 'S' : ''}</>
                : <><ShieldCheck size={11} /> CLEAR</>}
            </span>
            <button onClick={goOffShift}
                    className="text-[10px] px-2 py-1 rounded bg-black/60 text-white">
              End shift
            </button>
          </div>
        )}
      </div>

      {/* talk button */}
      <div className="px-4 py-4 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)]">
        <button
          disabled={!onShift || thinking}
          onPointerDown={startListening}
          onPointerUp={stopListening}
          onPointerLeave={() => listening && stopListening()}
          className="w-full py-5 rounded-2xl font-semibold text-base flex items-center justify-center gap-3 transition-all disabled:opacity-40 select-none touch-none active:scale-[0.98]"
          style={{
            background: listening ? 'var(--fail)' : thinking ? 'var(--bg-elevated)' : 'var(--cyan)',
            color: listening ? '#fff' : thinking ? 'var(--text-muted)' : '#000',
          }}
        >
          {thinking
            ? <><Loader2 size={20} className="animate-spin motion-reduce:animate-none" /> Thinking…</>
            : listening
            ? <><Mic size={20} /> Listening — release to send</>
            : <><Mic size={20} /> Hold to ask</>}
        </button>
        <p className="text-[10px] text-[var(--text-muted)] text-center mt-2">
          Try: “what is in front of me?” · “is this spacing right, check the doc?” ·
          “what should I do next?”
        </p>
      </div>

      {/* transcript */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {log.length === 0 && (
          <p className="text-xs text-[var(--text-muted)] text-center py-8">
            Everything the system says to you appears here, so you can re-read what you heard.
          </p>
        )}
        {log.map(e => (
          <div key={e.id}
               className={`rounded-xl px-3 py-2 ${e.who === 'worker' ? 'ml-8' : 'mr-8'}`}
               style={{
                 background: e.tone === 'hazard'
                   ? 'color-mix(in srgb, var(--fail) 16%, var(--bg-surface))'
                   : e.tone === 'warn'
                   ? 'color-mix(in srgb, var(--amber) 14%, var(--bg-surface))'
                   : 'var(--bg-surface)',
                 border: `1px solid ${e.tone === 'hazard' ? 'var(--fail)' : 'var(--border-subtle)'}`,
               }}>
            <div className="flex items-center gap-1.5 text-[9px] uppercase tracking-wider text-[var(--text-muted)] mb-0.5">
              {e.who === 'worker' ? <><Mic size={9} /> you</> : <><Volume2 size={9} /> FieldPilot</>}
              {e.meta && <span className="normal-case tracking-normal">· {e.meta}</span>}
            </div>
            <p className="text-[13px] leading-snug">{e.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
