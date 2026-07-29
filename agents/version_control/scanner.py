import base64
import numpy as np
import cv2
import re
import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

try:
    from paddleocr import PaddleOCR
    HAS_PADDLE = True
except ImportError:
    HAS_PADDLE = False

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

DRAWING_NUMBER_PATTERNS = [
    r"DWG\s*NO[.:]?\s*([A-Z0-9\-]+)",
    r"DRAWING\s*NO[.:]?\s*([A-Z0-9\-]+)", 
    r"DRAWING\s*NUMBER[.:]?\s*([A-Z0-9\-]+)",
    r"DOC\s*NO[.:]?\s*([A-Z0-9\-]+)",
    r"PROJECT\s*NO[.:]?\s*([A-Z0-9\-]+)",
]

REVISION_PATTERNS = [
    r"REV[.:]?\s*([A-Z0-9]+)",
    r"REVISION[.:]?\s*([A-Z0-9]+)",
    r"ISS[UE]*[.:]?\s*([A-Z0-9]+)",
    r"R\.?\s*([0-9]+)",          # catches R3, R.3
]

DATE_PATTERNS = [
    r"DATE[.:]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
    r"DATED[.:]?\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
    r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})",
]

def extract_field(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None

class GeminiOCR:
    """
    Real OCR fallback for when PaddleOCR isn't available — which is every
    environment running Python 3.14 right now: `pip install paddleocr`
    genuinely fails here (paddlepaddle has no distribution for cp314, and
    paddleocr's own build breaks on an unrelated Cython/PyYAML issue,
    confirmed by actually attempting the install rather than assuming).
    MockPaddleOCR previously returned the exact same hardcoded string
    ("DWG NO: S-101 REV: R3 DATE: 2024-08-10") regardless of the actual
    image — this instead sends the real frame to Gemini vision (same
    GEMINI_API_KEY already used by agents/vision/vlm_analyzer.py and
    agents/voice/tts.py) and reads back the real title-block text.
    Returns the same nested list shape PaddleOCR.ocr() returns so
    VersionControlScanner.extract_text() doesn't need to know which
    backend produced it.
    """
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY")
        self.model = os.getenv("GEMINI_VLM_MODEL", "gemini-flash-latest")

    def ocr(self, img, cls=True):
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set — GeminiOCR cannot read drawing frames.")
            return [[[None, ("", 0.0)]]]
        try:
            ok, buf = cv2.imencode(".jpg", img)
            if not ok:
                return [[[None, ("", 0.0)]]]
            b64 = base64.b64encode(buf).decode()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
            payload = {
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"text": "Read the drawing title block in this image. Return ONLY the raw text you see, verbatim, preserving labels like DWG NO, REV, REVISION, DATE if present. No commentary, no markdown."},
                        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    ],
                }],
                "generationConfig": {"temperature": 0.0},
            }
            resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=20)
            resp.raise_for_status()
            text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            confidence = 0.9 if text else 0.0
            return [[[None, (text, confidence)]]]
        except Exception as e:
            logger.error(f"GeminiOCR failed: {e}")
            return [[[None, ("", 0.0)]]]

class VersionControlScanner:
    _instance = None
    _ocr = None

    def __init__(self):
        if VersionControlScanner._ocr is None:
            if HAS_PADDLE:
                VersionControlScanner._ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
            else:
                VersionControlScanner._ocr = GeminiOCR()

        self.ocr = VersionControlScanner._ocr

        self.uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        # Matches docker-compose.yml's real NEO4J_AUTH — "password" never
        # matched the actual container (same stale-default bug fixed
        # elsewhere this session in ingestor.py/predictor.py).
        self.password = os.getenv("NEO4J_PASSWORD", "askthewall_dev")

    @classmethod
    def warmup(cls):
        instance = cls()
        if HAS_PADDLE:
            # A real dummy inference is worth it here — it's what actually
            # loads PaddleOCR's model weights into memory, avoiding a slow
            # first real request.
            logger.info("Warming up PaddleOCR...")
            dummy = np.zeros((100, 100, 3), dtype=np.uint8)
            instance.ocr.ocr(dummy, cls=True)
            logger.info("PaddleOCR warmup complete")
        else:
            # GeminiOCR has no local model to load — there's nothing to
            # warm up, and firing a real API call with a meaningless blank
            # image on every server start would just waste a request.
            logger.info("Version Control OCR backend: Gemini (no local model to warm up).")

    def _decode_image(self, b64_string: str) -> np.ndarray:
        if "," in b64_string:
            b64_string = b64_string.split(",")[1]
        img_data = base64.b64decode(b64_string)
        nparr = np.frombuffer(img_data, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    def extract_text(self, image: np.ndarray) -> tuple[str, float]:
        result = self.ocr.ocr(image, cls=True)
        if not result or not result[0]:
            return "", 0.0
            
        full_text = []
        confidences = []
        for line in result[0]:
            if line and len(line) == 2:
                text, conf = line[1]
                full_text.append(text)
                confidences.append(conf)
                
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return " ".join(full_text), avg_conf

    def lookup_neo4j(self, drawing_number: str) -> dict | None:
        try:
            driver = GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            with driver.session() as session:
                query = """
                MATCH (d:Drawing {number: $drawing_number})
                WHERE NOT (d)-[:SUPERSEDES]->(:Drawing)
                RETURN d.revision as latest_revision, 
                       d.approved_date as approved_date,
                       d.key_changes as key_changes
                """
                result = session.run(query, drawing_number=drawing_number)
                record = result.single()
                
            driver.close()
            
            if record:
                return {
                    "number": drawing_number,
                    "revision": record["latest_revision"],
                    "date": record["approved_date"],
                    "key_changes": record["key_changes"],
                    "approved_by": "David Park, SE" # Hardcoded for demo if not in graph
                }
        except Exception as e:
            logger.error(f"Neo4j Lookup Failed: {e}")
            # Fallback to mock database if Neo4j is completely down/empty, as per prompt instruction
            pass
            
        # Fallback Mock if Neo4j empty or down
        mock_db = {
            "S-101": {"number": "S-101", "revision": "R5", "date": "2024-11-02", "key_changes": "Rebar spacing in Zone A12 changed from 200mm to 150mm", "approved_by": "David Park, SE"},
            "S-102": {"number": "S-102", "revision": "R3", "date": "2024-10-15", "key_changes": "Column C4 lap splice clarified", "approved_by": "Sarah Chen, PE"}
        }
        return mock_db.get(drawing_number)

    def scan_drawing(self, frame_b64: str) -> dict:
        # Handle unreadable early
        try:
            image = self._decode_image(frame_b64)
        except Exception:
            return self._build_uncertain_alert("Cannot decode image. Improve lighting and rescan.")

        text, confidence = self.extract_text(image)
        
        # Test Case 4: UNREADABLE
        if confidence < 0.6 or not text.strip():
            return self._build_uncertain_alert("Cannot read drawing. Improve lighting and rescan.")

        # Extract fields
        number = extract_field(text, DRAWING_NUMBER_PATTERNS)
        revision = extract_field(text, REVISION_PATTERNS)
        date = extract_field(text, DATE_PATTERNS)

        if not number:
            return self._build_uncertain_alert("Drawing number not found in frame. Verify with engineer.")

        # Test Case 3: UNKNOWN
        current_approved = self.lookup_neo4j(number)
        if not current_approved:
            return self._build_uncertain_alert(f"Drawing {number} not found in project database. Verify with engineer.")

        # Compare Revisions
        detected_rev = revision if revision else "Unknown"
        
        # Simple string comparison (e.g., R3 vs R5)
        # In a real system, you'd strip non-numeric or parse semantic versioning
        is_outdated = False
        if detected_rev != "Unknown":
            # Strip 'R' or 'REV' prefix for numeric comparison if possible
            det_num = re.sub(r'[^0-9]', '', detected_rev)
            app_num = re.sub(r'[^0-9]', '', current_approved['revision'])
            if det_num and app_num:
                if int(det_num) < int(app_num):
                    is_outdated = True
            else:
                if detected_rev < current_approved['revision']:
                    is_outdated = True

        detected_payload = {
            "number": number,
            "revision": detected_rev,
            "date": date if date else "Unknown",
            "ocr_confidence": round(confidence, 2)
        }

        # Test Case 1: OUTDATED
        if is_outdated:
            return {
                "drawing_detected": detected_payload,
                "current_approved": current_approved,
                "status": "OUTDATED",
                "alert": {
                    "severity": "CRITICAL",
                    "glasses_audio": f"WARNING. Drawing {number} Revision {detected_rev} detected. Current approved revision is {current_approved['revision']}. DO NOT BUILD from this drawing.",
                    "worker_message": f"Stop. You are holding drawing {number}-{detected_rev}. Latest approved is {current_approved['revision']} ({current_approved['date']}). {current_approved['key_changes']}.",
                    "action": "STOP_WORK_UNTIL_CORRECT_DRAWING_OBTAINED"
                }
            }
        
        # Test Case 2: CURRENT
        return {
            "drawing_detected": detected_payload,
            "current_approved": current_approved,
            "status": "CURRENT",
            "alert": {
                "severity": "PASS",
                "worker_message": "Drawing is up to date.",
                "action": "PROCEED"
            }
        }

    def _build_uncertain_alert(self, msg: str) -> dict:
        return {
            "status": "UNCERTAIN",
            "alert": {
                "severity": "WARNING",
                "worker_message": msg,
                "action": "MANUAL_VERIFICATION_REQUIRED"
            }
        }
