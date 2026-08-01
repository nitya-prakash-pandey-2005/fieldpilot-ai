import { NativeModules, Platform } from 'react-native';

/**
 * Where the FieldPilot API lives, resolved in this order:
 *
 *   1. EXPO_PUBLIC_API_URL          explicit override, always wins
 *   2. the Metro bundler's host     auto-detected (see below)
 *   3. a per-platform fallback      last resort
 *
 * A user-set value from the Profile screen overrides all of this at runtime;
 * this module only supplies the default so the app works before anyone has
 * typed anything.
 *
 * Why auto-detect: the previous defaults were `10.0.2.2` on Android and
 * `localhost` on iOS. Both are correct only on an EMULATOR — `10.0.2.2` is the
 * Android emulator's alias for the host machine, and `localhost` on a physical
 * phone is the phone itself. On real hardware over WiFi (the actual demo setup,
 * and the only setup that works with a real camera) every request failed until
 * someone hand-typed the dev machine's LAN IP into Profile. The production
 * fallback was a hardcoded `192.168.1.6`, which is whatever address one laptop
 * happened to have on one network.
 */

function bundlerHost(): string | null {
  // In development the JS bundle is served by Metro from the dev machine, so
  // the bundle URL contains that machine's address AS REACHABLE FROM THIS
  // DEVICE. The API runs on the same machine, so this is the right host in
  // every case at once: physical phone (LAN IP), Android emulator (10.0.2.2),
  // iOS simulator (localhost). No per-platform guessing needed.
  try {
    const scriptURL = (NativeModules as any)?.SourceCode?.scriptURL;
    if (typeof scriptURL !== 'string') return null;
    const match = scriptURL.match(/^[a-z]+:\/\/([^/:]+)/i);
    const host = match?.[1];
    // A bundle served from the device itself (a standalone build) tells us
    // nothing about where the API is.
    if (!host || host === 'localhost' || host === '127.0.0.1') {
      return Platform.OS === 'web' ? host ?? null : null;
    }
    return host;
  } catch {
    return null;
  }
}

function webHost(): string | null {
  if (Platform.OS !== 'web') return null;
  try {
    return typeof window !== 'undefined' ? window.location.hostname : null;
  } catch {
    return null;
  }
}

const API_PORT = process.env.EXPO_PUBLIC_API_PORT ?? '8000';

function resolveApiUrl(): string {
  const explicit = process.env.EXPO_PUBLIC_API_URL;
  if (explicit) return explicit.replace(/\/+$/, '');

  const host = webHost() ?? bundlerHost();
  if (host) return `http://${host}:${API_PORT}`;

  // Nothing detectable. These only apply to a standalone build with no
  // EXPO_PUBLIC_API_URL baked in, which is a misconfiguration — set the env
  // var at build time rather than relying on this.
  if (Platform.OS === 'android') return `http://10.0.2.2:${API_PORT}`;
  return `http://localhost:${API_PORT}`;
}

const API_BASE_URL = resolveApiUrl();

if (__DEV__) {
  // Printed on every start: when the phone can't reach the backend this is the
  // first thing worth checking, and it saves a round of "is it the firewall or
  // the URL?" during a demo.
  console.log(`[FieldPilot] API base URL: ${API_BASE_URL}`);
  console.log('[FieldPilot] Override it in Profile, or set EXPO_PUBLIC_API_URL.');
}

const config = {
  API_BASE_URL,
  WS_BASE_URL: API_BASE_URL.replace(/^http/, 'ws'),
  API_PORT,
  /** Exposed so Profile can show what was auto-detected before any override. */
  detectedApiUrl: API_BASE_URL,
};

export default config;
