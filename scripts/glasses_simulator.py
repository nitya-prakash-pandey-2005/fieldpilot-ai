import cv2
import requests
import base64
import pyttsx3
import time
import threading

API_URL = "http://localhost:8000"
LANGUAGE = "en"
ZONE_ID = "A12"
SAMPLE_INTERVAL = 3.0  # seconds between frames

# TTS engine setup
try:
    tts_engine = pyttsx3.init()
    tts_engine.setProperty('rate', 150)
    tts_available = True
except Exception as e:
    print(f"TTS initialization failed: {e}")
    tts_available = False

def speak(text: str):
    if not tts_available:
        print(f"[SPEAKING]: {text}")
        return
    def _speak():
        tts_engine.say(text)
        tts_engine.runAndWait()
    threading.Thread(target=_speak, daemon=True).start()

def encode_frame(frame) -> str:
    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return base64.b64encode(buffer.tobytes()).decode()

def draw_hud(frame, result: dict):
    """Draw AR glasses-style HUD overlay"""
    h, w = frame.shape[:2]
    overlay = frame.copy()
    
    urgency = result.get("urgency", "low").lower()
    
    # Status bar color
    colors = {
        "critical": (0, 0, 255),
        "high": (0, 80, 255),
        "medium": (0, 165, 255),
        "low": (0, 180, 50)
    }
    color = colors.get(urgency, (0, 180, 50))
    
    # Top bar
    cv2.rectangle(overlay, (0,0), (w,70), color, -1)
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
    
    # Zone label
    cv2.putText(frame, f"ZONE {ZONE_ID}", (15, 25), cv2.FONT_HERSHEY_DUPLEX, 0.65, (255,255,255), 1)
    
    # Status
    status = urgency.upper() if urgency != "low" else "MONITORING"
    cv2.putText(frame, f"FIELDPILOT AI - {status}", (w//2 - 140, 25), cv2.FONT_HERSHEY_DUPLEX, 0.65, (255,255,255), 1)
    
    # Hazards
    hazards = result.get("safety_hazards", [])
    if hazards:
        hazard_text = f"WARNING: {hazards[0]}"
        cv2.putText(frame, hazard_text, (15, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255,255,100), 1)
    
    # Scene description (bottom)
    scene = result.get("scene_description", "Waiting for analysis...")
    if len(scene) > 90:
        scene = scene[:87] + "..."
        
    cv2.rectangle(frame, (0, h-60), (w, h), (0,0,0), -1)
    cv2.putText(frame, scene, (15, h-35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200,200,200), 1)
    
    # Corner brackets (AR feel)
    thickness = 2
    length = 25
    bracket_color = (0, 210, 255)
    # Top-left
    cv2.line(frame,(80,80),(80+length,80), bracket_color, thickness)
    cv2.line(frame,(80,80),(80,80+length), bracket_color, thickness)
    # Top-right  
    cv2.line(frame,(w-80,80),(w-80-length,80), bracket_color, thickness)
    cv2.line(frame,(w-80,80),(w-80,80+length), bracket_color, thickness)
    # Bottom-left
    cv2.line(frame,(80,h-80),(80+length,h-80), bracket_color, thickness)
    cv2.line(frame,(80,h-80),(80,h-80-length), bracket_color, thickness)
    # Bottom-right
    cv2.line(frame,(w-80,h-80),(w-80-length,h-80), bracket_color, thickness)
    cv2.line(frame,(w-80,h-80),(w-80,h-80-length), bracket_color, thickness)
    # Draw bounding boxes if any
    detections = result.get("detections", {}).get("assets_detected", [])
    for det in detections:
        bbox = det.get("bounding_box", {})
        if bbox and all(k in bbox for k in ("x1", "y1", "x2", "y2")):
            x1, y1, x2, y2 = int(bbox["x1"]), int(bbox["y1"]), int(bbox["x2"]), int(bbox["y2"])
            label = det.get("asset_type", "Unknown")
            conf = det.get("confidence", 0.0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(frame, f"{label} {conf:.2f}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    return frame

def process_frame(frame_b64: str) -> dict:
    try:
        response = requests.post(
            f"{API_URL}/api/v1/vision/understand",
            json={
                "image": frame_b64,
                "zone_id": ZONE_ID,
                "language": LANGUAGE,
                "project_id": "P-001"
            },
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            scene = data.get("scene", {})
            scene["detections"] = data.get("detections", {})
            return scene
        else:
            print(f"API Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")
    return {}

def main():
    import os
    video_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'sample_construction.mp4')
    
    if os.path.exists(video_path):
        print(f"Using sample video: {video_path}")
        cap = cv2.VideoCapture(video_path)
    else:
        print("Sample video not found, falling back to webcam.")
        cap = cv2.VideoCapture(0)
        
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    if not cap.isOpened():
        print("Error: Could not open video source.")
        return
        
    print("🥽 FIELDPILOT AI - Glasses Simulator")
    print(f"   API: {API_URL}")
    print("   Press Q to quit")
    
    last_result = {
        "scene_description": "Monitoring...",
        "urgency": "low",
        "safety_hazards": [],
        "spoken_response": ""
    }
    last_spoken = ""
    is_processing = False
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Add slight delay so video doesn't play too fast
        time.sleep(0.03) 
        
        if not is_processing:
            is_processing = True
            frame_b64 = encode_frame(frame)
            
            def process_bg():
                nonlocal last_result, last_spoken, is_processing
                result = process_frame(frame_b64)
                if result:
                    last_result = result
                    spoken = result.get("spoken_response", "")
                    urgency = result.get("urgency", "low").lower()
                    if spoken and spoken != last_spoken and urgency in ["high", "critical", "medium"]:
                        speak(spoken)
                        last_spoken = spoken
                is_processing = False
                        
            threading.Thread(target=process_bg, daemon=True).start()
            
        display_frame = draw_hud(frame.copy(), last_result)
        cv2.imshow("FieldPilot AI Glasses View [Press Q to quit]", display_frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('v'):
            # Record audio query
            try:
                import sounddevice as sd
                import scipy.io.wavfile as wav
                import requests
                
                print("\n🎤 RECORDING FOR 5 SECONDS... SPEAK NOW!")
                fs = 44100
                duration = 5  # seconds
                recording = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='int16')
                sd.wait()
                print("✅ Recording complete. Sending to AI...")
                
                temp_wav = "query.wav"
                wav.write(temp_wav, fs, recording)
                
                def send_voice():
                    try:
                        with open(temp_wav, "rb") as f:
                            files = {"audio": ("query.wav", f, "audio/wav")}
                            data = {"project_id": "P-001", "zone_id": "A12"}
                            res = requests.post(f"{API_URL}/api/v1/voice/query", files=files, data=data)
                            if res.status_code == 200:
                                answer = res.json().get("response_text", "")
                                print(f"\n🧠 AI ANSWERS: {answer}")
                                speak(answer)
                    except Exception as e:
                        print(f"Voice API Error: {e}")
                
                threading.Thread(target=send_voice, daemon=True).start()
                
            except Exception as e:
                print(f"\n❌ Microphone error: {e}")
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
