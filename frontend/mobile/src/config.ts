import { Platform } from 'react-native';

const getApiUrl = () => {
  // Android emulator special alias
  if (__DEV__ && Platform.OS === 'android') {
    // Check if running in emulator vs physical device
    // Emulator uses 10.0.2.2, physical device needs LAN IP
    // For MVP we default to the emulator IP if the EXPO_PUBLIC_API_URL isn't set
    return process.env.EXPO_PUBLIC_API_URL ?? 'http://10.0.2.2:8000';
  }
  return process.env.EXPO_PUBLIC_API_URL ?? 'http://192.168.1.100:8000';
};

const config = {
  API_BASE_URL: getApiUrl(),
  WS_BASE_URL: getApiUrl().replace('http', 'ws'),
};

export default config;
