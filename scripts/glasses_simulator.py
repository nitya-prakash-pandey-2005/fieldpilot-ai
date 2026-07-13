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
            return response.json().get("scene", {})
        else:
            print(f"API Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")
    return {}

def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return
        
    print("🥽 FIELDPILOT AI - Glasses Simulator")
    print(f"   API: {API_URL}")
    print("   Press Q to quit")
    
    last_process = 0
    last_result = {
        "scene_description": "Monitoring...",
        "urgency": "low",
        "safety_hazards": [],
        "spoken_response": ""
    }
    last_spoken = ""
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        now = time.time()
        
        if now - last_process >= SAMPLE_INTERVAL:
            frame_b64 = encode_frame(frame)
            
            def process_bg():
                nonlocal last_result, last_spoken
                result = process_frame(frame_b64)
                if result:
                    last_result = result
                    spoken = result.get("spoken_response", "")
                    urgency = result.get("urgency", "low").lower()
                    if spoken and spoken != last_spoken and urgency in ["high", "critical", "medium"]:
                        speak(spoken)
                        last_spoken = spoken
                        
            threading.Thread(target=process_bg, daemon=True).start()
            last_process = now
            
        display_frame = draw_hud(frame.copy(), last_result)
        cv2.imshow("FieldPilot AI Glasses View [Press Q to quit]", display_frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
            
    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
