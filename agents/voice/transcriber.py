import groq
import base64
import tempfile
import os

class VoiceAgent:
    def __init__(self):
        self.api_key = os.environ.get("GROQ_API_KEY") or "dummy-key-for-demo"
        self.client = groq.Groq(api_key=self.api_key)
    
    async def transcribe(
        self, 
        audio_bytes: bytes,
        filename: str = "audio.webm"
    ) -> dict:
        
        with tempfile.NamedTemporaryFile(
            suffix=f".{filename.split('.')[-1]}",
            delete=False
        ) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        
        try:
            with open(tmp_path, "rb") as audio_file:
                transcription = \
                    self.client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        response_format="verbose_json"
                    )
            # Some versions of groq package return dict, some return objects
            if hasattr(transcription, "text"):
                return {
                    "text": transcription.text,
                    "language": getattr(transcription, "language", "en"),
                    "duration": getattr(transcription, "duration", 0)
                }
            else:
                return {
                    "text": transcription.get("text", ""),
                    "language": transcription.get("language", "en"),
                    "duration": transcription.get("duration", 0)
                }
        finally:
            os.unlink(tmp_path)
    
    async def text_to_speech(
        self,
        text: str,
        language: str = "en"
    ) -> bytes:
        # Groq TTS
        response = self.client.audio.speech.create(
            model="playai-tts",
            voice="Aaliyah",
            input=text[:500]  # TTS limit
        )
        return response.content
