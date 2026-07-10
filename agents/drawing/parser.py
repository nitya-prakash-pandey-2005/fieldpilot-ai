import os
import sys
import json
from dotenv import load_dotenv

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))
from utils.llm_client import get_llm_response

# Load environment variables
load_dotenv()
LLAMA_CLOUD_API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")

class DocumentParser:
    def __init__(self):
        # Initialize parsers lazily to avoid heavy overhead on module load
        self.docling_doc_converter = None
        self.llama_parser = None

    def _get_docling(self):
        if self.docling_doc_converter is None:
            # Real import
            from docling.document_converter import DocumentConverter
            self.docling_doc_converter = DocumentConverter()
        return self.docling_doc_converter
        
    def _get_llama_parse(self):
        if not LLAMA_CLOUD_API_KEY:
            return None
        if self.llama_parser is None:
            # Real import
            from llama_parse import LlamaParse
            self.llama_parser = LlamaParse(api_key=LLAMA_CLOUD_API_KEY, result_type="markdown")
        return self.llama_parser

    def parse(self, file_path: str, is_tabular: bool = False):
        """
        Strategy Pattern:
        1. If it's heavily tabular and LLAMA_CLOUD_API_KEY exists, try LlamaParse.
        2. Otherwise, use Docling (local & free).
        3. If Docling fails or has low confidence, and LlamaParse is available, fallback to LlamaParse.
        """
        llama = self._get_llama_parse()
        
        if is_tabular and llama:
            print("Using LlamaParse for explicit tabular document...")
            return self._parse_with_llama(file_path, llama)
            
        print("Using Docling as primary parser...")
        result, confidence = self._parse_with_docling(file_path)
        
        if confidence < 0.6 and llama:
            print(f"Docling confidence low ({confidence}). Falling back to LlamaParse...")
            return self._parse_with_llama(file_path, llama)
            
        return result

    def _parse_with_docling(self, file_path: str):
        try:
            converter = self._get_docling()
            result = converter.convert(file_path)
            # docling result contains the exported markdown
            text = result.document.export_to_markdown()
            # Rough confidence proxy - if text is very short for a pdf, it might have failed to OCR/extract
            confidence = 1.0 if len(text) > 100 else 0.4
            return text, confidence
        except Exception as e:
            print(f"Docling parsing error: {e}")
            return "", 0.0

    def _parse_with_llama(self, file_path: str, llama_parser):
        try:
            documents = llama_parser.load_data(file_path)
            text = "\n\n".join([doc.text for doc in documents])
            return text
        except Exception as e:
            print(f"LlamaParse error: {e}")
            return ""

async def extract_dimensions_from_text(markdown_text: str, drawing_number: str) -> list[dict]:
    """
    Real LLM extraction logic. Uses get_llm_response to structure JSON.
    """
    prompt = f"""
    Extract ALL dimensional specifications 
    from this engineering drawing text.
    Return ONLY a JSON array. No explanation.
    
    Drawing: {drawing_number}
    Content: {markdown_text[:3000]}
    
    Format:
    [
      {{
        "element_type": "rebar",
        "parameter": "spacing",
        "value": 150,
        "unit": "mm", 
        "tolerance_min": 140,
        "tolerance_max": 160,
        "zone": "A12",
        "standard_ref": "ACI 318-19"
      }}
    ]
    
    Return [] if no specs found.
    """
    
    response = get_llm_response(
        system_prompt="You are a JSON extraction API.",
        user_prompt=prompt,
        temperature=0.1
    )
    
    try:
        # Strip any markdown fences
        clean = response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        return json.loads(clean)
    except:
        return []
