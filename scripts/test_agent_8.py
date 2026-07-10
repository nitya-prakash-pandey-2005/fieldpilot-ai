import sys
import os
import base64
import numpy as np
import cv2

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))
from agents.version_control.scanner import VersionControlScanner

def create_dummy_image(text: str) -> str:
    # Create a simple white image with text
    img = np.ones((200, 600, 3), dtype=np.uint8) * 255
    cv2.putText(img, text, (10, 100), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    _, buffer = cv2.imencode('.png', img)
    return base64.b64encode(buffer).decode('utf-8')

def create_blurry_image() -> str:
    # Create a noisy/blurry image that OCR will fail on
    img = np.random.randint(0, 255, (200, 600, 3), dtype=np.uint8)
    _, buffer = cv2.imencode('.png', img)
    return base64.b64encode(buffer).decode('utf-8')

def run_tests():
    scanner = VersionControlScanner()
    
    print("\n--- Test 1: OUTDATED (S-101 R3 vs R5) ---")
    # Mock OCR for Test 1
    scanner.extract_text = lambda img: ("DWG NO: S-101 REV: R3 DATE: 2024-08-10", 0.99)
    b64_1 = create_dummy_image("DWG NO: S-101 REV: R3")
    res1 = scanner.scan_drawing(b64_1)
    print(res1)
    assert res1["status"] == "OUTDATED", f"Expected OUTDATED, got {res1['status']}"

    print("\n--- Test 2: CURRENT (S-101 R5 vs R5) ---")
    scanner.extract_text = lambda img: ("DWG NO: S-101 REV: R5 DATE: 2024-11-02", 0.99)
    b64_2 = create_dummy_image("DWG NO: S-101 REV: R5")
    res2 = scanner.scan_drawing(b64_2)
    print(res2)
    assert res2["status"] == "CURRENT", f"Expected CURRENT, got {res2['status']}"

    print("\n--- Test 3: UNKNOWN (ZZ-999) ---")
    scanner.extract_text = lambda img: ("DWG NO: ZZ-999 REV: R1 DATE: 2024-01-01", 0.95)
    b64_3 = create_dummy_image("DWG NO: ZZ-999 REV: R1")
    res3 = scanner.scan_drawing(b64_3)
    print(res3)
    assert res3["status"] == "UNCERTAIN", f"Expected UNCERTAIN, got {res3['status']}"

    print("\n--- Test 4: UNREADABLE (Low Confidence) ---")
    # Native extract text will fail on random noise (if paddle runs) or we just force the mock to return low conf
    scanner.extract_text = lambda img: ("GARBAGE", 0.4)
    b64_4 = create_blurry_image()
    res4 = scanner.scan_drawing(b64_4)
    print(res4)
    assert res4["status"] == "UNCERTAIN", f"Expected UNCERTAIN, got {res4['status']}"
    assert "Cannot read drawing" in res4["alert"]["worker_message"]

    print("\n✅ All 4 Agent 8 Test Cases Passed!")

if __name__ == "__main__":
    run_tests()
