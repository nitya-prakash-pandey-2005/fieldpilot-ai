import React, { useState, useEffect, useRef } from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ActivityIndicator, Animated, Dimensions, Vibration } from 'react-native';
import { Camera as CameraIcon, CheckCircle, XCircle, AlertTriangle } from 'lucide-react-native';
import * as Haptics from 'expo-haptics';
import { CameraView, useCameraPermissions } from 'expo-camera';
import config from '../config';
import { useTheme } from '../context/ThemeContext';

const { height: SCREEN_HEIGHT } = Dimensions.get('window');

export function ScanScreen() {
  const { colors, apiBaseUrl } = useTheme();
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<any>(null);
  
  // Animation value for the scan line
  const scanAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    // Infinite loop animation for scan line
    Animated.loop(
      Animated.sequence([
        Animated.timing(scanAnim, {
          toValue: 1,
          duration: 2000,
          useNativeDriver: true,
        }),
        Animated.timing(scanAnim, {
          toValue: 0,
          duration: 0,
          useNativeDriver: true,
        })
      ])
    ).start();
  }, [scanAnim]);

  const handleScan = async () => {
    setAnalyzing(true);
    setResult(null);
    
    try {
      const baseUrl = apiBaseUrl || config.API_BASE_URL;
      
      let base64Image = "";
      if (cameraRef.current) {
          const photo = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.3 });
          base64Image = photo.base64;
      }
      
      const response = await fetch(`${baseUrl}/api/v1/vision/understand`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Bypass-Tunnel-Reminder': 'true'
        },
        body: JSON.stringify({
          image: base64Image,
          zone_id: "A12",
          language: "en",
          project_id: "P-001"
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
      
      // Map VLM response format to our overlay UI format
      const isPass = data.scene?.urgency === "low";
      const isCritical = data.scene?.urgency === "critical";
      
      triggerResult({
        result: isPass ? "PASS" : "FAIL",
        severity: isCritical ? "CRITICAL" : "HIGH",
        explanation: {
          worker_message: data.scene?.spoken_response || data.scene?.scene_description || "Analyzed successfully."
        }
      });
      
    } catch (error: any) {
      console.error("Scan error", error);
      triggerResult({
        result: "FAIL",
        severity: "ERROR",
        explanation: {
          worker_message: `Network request failed: ${error.message}`
        }
      });
    } finally {
      setAnalyzing(false);
    }
  };

  const triggerResult = (data: any) => {
    setResult(data);
    if (data.result === "PASS") {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      setTimeout(() => setResult(null), 2500); // Auto dismiss
    } else {
      Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
    }
  };

  const renderResultOverlay = () => {
    if (!result) return null;

    const isPass = result.result === "PASS";
    const isCritical = result.severity === "CRITICAL";

    const overlayStyle = [
      styles.fullScreenOverlay,
      isPass ? styles.passBg : isCritical ? styles.criticalBg : styles.failBg
    ];

    return (
      <View style={overlayStyle}>
        <View style={styles.overlayContent}>
          {isPass ? (
            <CheckCircle color="#FFF" size={80} />
          ) : isCritical ? (
            <AlertTriangle color="#FFF" size={80} style={styles.pulsingIcon} />
          ) : (
            <XCircle color="#FFF" size={80} style={styles.pulsingIcon} />
          )}

          <Text style={styles.overlayTitle}>
            {isPass ? "COMPLIANT" : isCritical ? "STOP WORK" : "VIOLATION"}
          </Text>

          {!isPass && (
            <Text style={styles.overlayText}>
              {result.explanation?.worker_message}
            </Text>
          )}

          {!isPass && (
            <TouchableOpacity 
              style={styles.ackButton}
              onPress={() => setResult(null)}
            >
              <Text style={styles.ackButtonText}>ACKNOWLEDGE</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>
    );
  };

  if (!permission) {
    return <View style={[styles.container, { backgroundColor: colors.bg, justifyContent: 'center' }]}><ActivityIndicator /></View>;
  }

  if (!permission.granted) {
    return (
      <View style={[styles.container, { backgroundColor: colors.bg, justifyContent: 'center', alignItems: 'center', padding: 20 }]}>
        <Text style={{ color: colors.text, textAlign: 'center', marginBottom: 20, fontSize: 16 }}>We need your permission to show the camera</Text>
        <TouchableOpacity style={[styles.ackButton, { backgroundColor: colors.primary }]} onPress={requestPermission}>
          <Text style={[styles.ackButtonText, { color: '#FFF' }]}>GRANT PERMISSION</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor: colors.bg }]}>
      {/* Real Camera Viewfinder */}
      <View style={[styles.cameraView, { backgroundColor: colors.surface, borderColor: colors.border }]}>
        <CameraView ref={cameraRef} style={StyleSheet.absoluteFillObject} facing="back" />
        
        <View style={[styles.testModeBadge, { backgroundColor: colors.warningSoft, borderColor: colors.warning }]}>
          <Text style={[styles.testModeText, { color: colors.warning }]}>TEST MODE: ON</Text>
        </View>
        
        {/* Corner Brackets */}
        <View style={[styles.corner, styles.tl, { borderColor: colors.cyan }]} />
        <View style={[styles.corner, styles.tr, { borderColor: colors.cyan }]} />
        <View style={[styles.corner, styles.bl, { borderColor: colors.cyan }]} />
        <View style={[styles.corner, styles.br, { borderColor: colors.cyan }]} />

        {/* Scanning Line Overlay */}
        <Animated.View 
          style={[
            styles.scanLine,
            {
              backgroundColor: colors.cyan,
              shadowColor: colors.cyan,
              transform: [{
                translateY: scanAnim.interpolate({
                  inputRange: [0, 1],
                  outputRange: [0, SCREEN_HEIGHT - 200]
                })
              }]
            }
          ]} 
        />
        
        <View style={styles.targetBox}>
          <Text style={[styles.overlayTag, { backgroundColor: colors.cyan, color: '#000' }]}>ALIGN OBJECT IN FRAME</Text>
        </View>
      </View>

      {/* Capture Button */}
      <View style={styles.controls}>
        <TouchableOpacity 
          style={[styles.captureButton, { backgroundColor: colors.cyan }]} 
          onPress={handleScan}
          disabled={analyzing}
        >
          {analyzing ? (
            <ActivityIndicator color="#0A0A0F" size="large" />
          ) : (
            <CameraIcon color="#0A0A0F" size={32} />
          )}
        </TouchableOpacity>
        <Text style={styles.controlText}>ANALYZE FRAME</Text>
      </View>

      {/* Result Overylay takes over entire screen */}
      {renderResultOverlay()}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0A0A0F', // deep space black
  },
  cameraView: {
    flex: 1,
    borderWidth: 2,
    borderColor: '#1E1E2E',
    margin: 16,
    marginTop: 40,
    borderRadius: 8,
    position: 'relative',
    backgroundColor: '#12121A', // darker mock camera
    overflow: 'hidden'
  },
  testModeBadge: {
    position: 'absolute',
    top: 16,
    alignSelf: 'center',
    backgroundColor: 'rgba(255, 179, 0, 0.2)',
    borderColor: '#FFB300',
    borderWidth: 1,
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 12,
    zIndex: 20
  },
  testModeText: {
    color: '#FFB300',
    fontSize: 12,
    fontWeight: 'bold',
    letterSpacing: 2
  },
  // Scanner specs
  scanLine: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    height: 2,
    backgroundColor: '#00D4FF',
    shadowColor: '#00D4FF',
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.6,
    shadowRadius: 10,
    elevation: 5,
    zIndex: 10
  },
  corner: {
    position: 'absolute',
    width: 20,
    height: 20,
    borderColor: '#00D4FF',
  },
  tl: { top: 20, left: 20, borderTopWidth: 2, borderLeftWidth: 2 },
  tr: { top: 20, right: 20, borderTopWidth: 2, borderRightWidth: 2 },
  bl: { bottom: 20, left: 20, borderBottomWidth: 2, borderLeftWidth: 2 },
  br: { bottom: 20, right: 20, borderBottomWidth: 2, borderRightWidth: 2 },
  
  targetBox: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center'
  },
  overlayTag: {
    color: '#0A0A0F',
    backgroundColor: '#00D4FF',
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 4,
    fontWeight: '900',
    fontSize: 16,
    letterSpacing: 1
  },
  
  controls: {
    height: 140,
    justifyContent: 'center',
    alignItems: 'center',
    paddingBottom: 20,
  },
  captureButton: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: '#00D4FF',
    justifyContent: 'center',
    alignItems: 'center',
    marginBottom: 12,
    minHeight: 48, // Touch target spec
    minWidth: 48
  },
  controlText: {
    color: '#888',
    fontSize: 14,
    fontWeight: '800',
    letterSpacing: 2
  },

  // Full screen results
  fullScreenOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 100,
    padding: 24,
  },
  passBg: {
    backgroundColor: 'rgba(0, 200, 81, 0.85)',
  },
  failBg: {
    backgroundColor: 'rgba(255, 59, 59, 0.90)',
  },
  criticalBg: {
    backgroundColor: 'rgba(255, 59, 59, 0.95)',
    // Fake warning stripes by setting border in a real app, keeping it solid red for now
  },
  overlayContent: {
    alignItems: 'center',
    width: '100%',
  },
  pulsingIcon: {
    // In React Native, pulsing requires animated component, standard icon for now
  },
  overlayTitle: {
    color: '#FFF',
    fontSize: 32,
    fontWeight: '900',
    marginTop: 24,
    marginBottom: 16,
    textAlign: 'center',
  },
  overlayText: {
    color: '#FFF',
    fontSize: 18,
    lineHeight: 28,
    textAlign: 'center',
    fontWeight: '600',
    marginBottom: 40,
  },
  ackButton: {
    backgroundColor: '#FFF',
    paddingVertical: 16,
    paddingHorizontal: 32,
    borderRadius: 30,
    minHeight: 56, // Accessible touch target
    width: '100%',
    alignItems: 'center'
  },
  ackButtonText: {
    color: '#FF3B3B',
    fontSize: 16,
    fontWeight: '900',
    letterSpacing: 1
  }
});
