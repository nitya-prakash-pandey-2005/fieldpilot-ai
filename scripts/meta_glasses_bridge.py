import cv2
import time
import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("API_URL", "http://localhost:8000/api/v1/vision/analyze")
CAPTURE_INTERVAL = 2.0  # seconds between frames

def stream_glasses():
    print("Initializing Meta Glasses (simulated via Webcam)...")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("Error: Could not open webcam.")
        return

    print(f"Streaming to {API_URL} at {1/CAPTURE_INTERVAL} FPS...")
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("Failed to capture frame")
                continue

            # Show the view from the "glasses"
            cv2.imshow('Meta Glasses POV', frame)
            
            # Save frame temporarily
            temp_path = "temp_glasses_frame.jpg"
            cv2.imwrite(temp_path, frame)
            
            try:
                with open(temp_path, 'rb') as f:
                    files = {'file': ('frame.jpg', f, 'image/jpeg')}
                    response = requests.post(API_URL, files=files)
                    
                if response.status_code == 200:
                    result = response.json()
                    # In a real setup, we would send audio feedback to the glasses here
                    if result.get("results", {}).get("assets_detected"):
                        print(f"Server analyzed frame: {len(result['results']['assets_detected'])} assets found.")
                    else:
                        print("Server analyzed frame: No assets detected.")
                else:
                    print(f"Server error: {response.status_code} - {response.text}")
                    
            except requests.exceptions.ConnectionError:
                print("Failed to connect to API. Is the server running?")
                
            time.sleep(CAPTURE_INTERVAL)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    except KeyboardInterrupt:
        print("Streaming stopped by user.")
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if os.path.exists("temp_glasses_frame.jpg"):
            os.remove("temp_glasses_frame.jpg")

if __name__ == "__main__":
    stream_glasses()
