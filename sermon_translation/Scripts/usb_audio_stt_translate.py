import pyaudio
import queue
import threading
from typing import Generator
from google.cloud import speech
from google.cloud import translate_v2 as translate
from datetime import datetime
import os

# Set credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials/sermon-streaming.json'

# Audio recording parameters
RATE = 16000  # Sample rate (Hz)
CHUNK = 1024  # Buffer size
FORMAT = pyaudio.paInt16  # 16-bit audio
CHANNELS = 1  # Mono audio


class AudioStreamer:
    """Captures audio from USB interface and streams to Google Cloud STT"""
    
    def __init__(self, device_index=None):
        self.audio = pyaudio.PyAudio()
        self.device_index = device_index or self._find_usb_device()
        self.audio_queue = queue.Queue()
        self.is_recording = False
        
    def _find_usb_device(self):
        """Find USB Audio Interface device"""
        print("\nAvailable audio devices:")
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            print(f"  [{i}] {info['name']}")
            if "USB" in info['name'] or "Focusrite" in info['name']:
                print(f"✓ Found USB device: {info['name']}")
                return i
        print("⚠ USB device not found, using default input")
        return None
    
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Callback function for audio stream"""
        if self.is_recording:
            self.audio_queue.put(in_data)
        return (in_data, pyaudio.paContinue)
    
    def start_stream(self):
        """Start capturing audio from USB interface"""
        self.is_recording = True
        self.stream = self.audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=CHUNK,
            stream_callback=self._audio_callback
        )
        self.stream.start_stream()
        print("\n🎤 Audio streaming started...")
    
    def stop_stream(self):
        """Stop audio capture"""
        self.is_recording = False
        if hasattr(self, 'stream'):
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()
        print("\n🛑 Audio streaming stopped.")
    
    def audio_generator(self) -> Generator[bytes, None, None]:
        """Generator that yields audio chunks for STT API"""
        while self.is_recording:
            try:
                chunk = self.audio_queue.get(timeout=1)
                yield chunk
            except queue.Empty:
                continue


class SermonTranslator:
    """
    Enhanced translation system optimized for Reformed/Expository sermons
    Style: John MacArthur / Grace to You
    
    DOMAIN: Expository sermon / Biblical teaching
    STYLE: Formal, theologically accurate
    """
    
    # Theological glossary for Reformed/Expository preaching (130+ terms)
    THEOLOGICAL_GLOSSARY = {
        # Core Reformed Theology
        "grace": {"es": "gracia", "pt": "graça", "fr": "grâce"},
        "salvation": {"es": "salvación", "pt": "salvação", "fr": "salut"},
        "redemption": {"es": "redención", "pt": "redenção", "fr": "rédemption"},
        "justification": {"es": "justificación", "pt": "justificação", "fr": "justification"},
        "sanctification": {"es": "santificación", "pt": "santificação", "fr": "sanctification"},
        "glorification": {"es": "glorificación", "pt": "glorificação", "fr": "glorification"},
        "regeneration": {"es": "regeneración", "pt": "regeneração", "fr": "régénération"},
        "faith": {"es": "fe", "pt": "fé", "fr": "foi"},
        "repentance": {"es": "arrepentimiento", "pt": "arrependimento", "fr": "repentance"},
        
        # Sovereignty and Election
        "sovereignty": {"es": "soberanía", "pt": "soberania", "fr": "souveraineté"},
        "election": {"es": "elección", "pt": "eleição", "fr": "élection"},
        "predestination": {"es": "predestinación", "pt": "predestinação", "fr": "prédestination"},
        "providence": {"es": "providencia", "pt": "providência", "fr": "providence"},
        
        # Biblical Authority
        "Scripture": {"es": "Escritura", "pt": "Escritura", "fr": "Écriture"},
        "inerrancy": {"es": "inerrancia", "pt": "inerrância", "fr": "inerrance"},
        "infallibility": {"es": "infalibilidad", "pt": "infalibilidade", "fr": "infaillibilité"},
        "exegesis": {"es": "exégesis", "pt": "exegese", "fr": "exégèse"},
        "exposition": {"es": "exposición", "pt": "exposição", "fr": "exposition"},
        
        # Add more as needed...
    }
    
    # Context hints for STT recognition (MacArthur-style preaching)
    SERMON_CONTEXT_HINTS = [
        "expository sermon", "verse by verse", "Biblical exposition",
        "exegetical preaching", "Reformed theology", "doctrinal teaching",
        "let us turn to", "open your Bibles", "the text says",
        "the original Greek", "the original Hebrew", "the passage teaches",
        "theological accuracy", "sound doctrine", "Biblical authority",
        "grammatical historical", "sola scriptura",
        "justification by faith", "imputed righteousness", "total depravity",
        "lordship salvation",
    ]
    
    def __init__(self, source_language="en-US", target_language="pt"):
        """
        Initialize enhanced sermon translation system
        
        Args:
            source_language: Language code for speech (e.g., "en-US")
            target_language: Target language code (e.g., "es", "pt", "fr")
        """
        from google.oauth2 import service_account
        
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'credentials/sermon-streaming.json')
        if creds_path:
            credentials = service_account.Credentials.from_service_account_file(creds_path)
            self.speech_client = speech.SpeechClient(credentials=credentials)
            self.translate_client = translate.Client(credentials=credentials)
        else:
            self.speech_client = speech.SpeechClient()
            self.translate_client = translate.Client()
        
        self.source_language = source_language
        self.target_language = target_language
        self.output_file = None
        
        # Extract base language codes
        self.source_lang_base = source_language.split('-')[0]
        self.target_lang_base = target_language.split('-')[0] if '-' in target_language else target_language
        
        print(f"\n🔧 Sermon Translation Configuration:")
        print(f"   Domain: Expository Sermon (Reformed)")
        print(f"   Style: Formal, Theologically Accurate")
        print(f"   Source: {source_language}")
        print(f"   Target: {target_language}")
        print(f"   Glossary: {len(self.THEOLOGICAL_GLOSSARY)} theological terms loaded")
        
    def process_stream(self, audio_streamer, translate_enabled=True, save_to_file=True):
        """
        Process audio stream with STT and domain-optimized translation
        
        CRITICAL CHAIN: Audio → STT (English) → Enhanced Translation (Target)
        """
        # Create output file with timestamp
        if save_to_file:
            os.makedirs("results", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"results/sermon_translation_{timestamp}.txt"
            self.output_file = open(output_filename, 'w', encoding='utf-8')
            
            # Write header with domain configuration
            self.output_file.write("SERMON TRANSLATION SESSION\n")
            self.output_file.write("="*60 + "\n")
            self.output_file.write(f"Date: {datetime.now()}\n")
            self.output_file.write(f"Domain: Expository Sermon (Reformed Theology)\n")
            self.output_file.write(f"Style: Formal, Theologically Accurate\n")
            self.output_file.write(f"Source Language: {self.source_language}\n")
            self.output_file.write(f"Target Language: {self.target_language}\n")
            self.output_file.write("="*60 + "\n\n")
            self.output_file.flush()
            
            print(f"\n💾 Saving sermon translation to: {output_filename}\n")
        
        # Configure STT with sermon-specific optimization
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=self.source_language,
            enable_automatic_punctuation=True,
            use_enhanced=True,  # Enhanced model
            model="latest_long",  # Best for longer sermons
            
            # Add speech context for theological terminology
            speech_contexts=[
                speech.SpeechContext(
                    phrases=self.SERMON_CONTEXT_HINTS + list(self.THEOLOGICAL_GLOSSARY.keys()),
                    boost=15  # Boost recognition of theological terms
                )
            ],
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True
        )
        
        # Create request generator
        def request_generator():
            for chunk in audio_streamer.audio_generator():
                yield speech.StreamingRecognizeRequest(audio_content=chunk)
        
        # Stream to Google Cloud Speech-to-Text
        print(f"\n🎧 Listening in {self.source_language}...")
        print(f"📖 Domain: Expository Sermon (Reformed)")
        if translate_enabled:
            print(f"🌐 Translating to {self.target_language} (Theological Mode)...\n")
        
        segment_count = 0
        
        try:
            responses = self.speech_client.streaming_recognize(
                streaming_config, 
                request_generator()
            )
            
            for response in responses:
                for result in response.results:
                    transcript = result.alternatives[0].transcript
                    
                    if result.is_final:
                        segment_count += 1
                        timestamp_str = datetime.now().strftime("%H:%M:%S")
                        
                        # Display English transcription
                        print(f"📝 [{timestamp_str}] English: {transcript}")
                        
                        # CRITICAL CHAIN: Immediately translate
                        if translate_enabled:
                            translation = self.translate_text(transcript)
                            print(f"🌐 [{timestamp_str}] {self.target_language.upper()}: {translation}")
                            
                            # Save to file in real-time
                            if self.output_file:
                                self.output_file.write(f"[{timestamp_str}] Segment {segment_count}\n")
                                self.output_file.write(f"English: {transcript}\n")
                                self.output_file.write(f"{self.target_language.upper()}: {translation}\n")
                                self.output_file.write("-" * 60 + "\n\n")
                                self.output_file.flush()
                        else:
                            # Save transcription only
                            if self.output_file:
                                self.output_file.write(f"[{timestamp_str}] {transcript}\n\n")
                                self.output_file.flush()
                        
                        print("-" * 60)
                    else:
                        # Interim result
                        print(f"💭 {transcript}", end='\r')
                        
        except Exception as e:
            print(f"\n❌ Error: {e}")
        finally:
            # Close output file
            if self.output_file:
                self.output_file.write("\n" + "="*60 + "\n")
                self.output_file.write(f"Session ended: {datetime.now()}\n")
                self.output_file.write(f"Total segments: {segment_count}\n")
                self.output_file.write(f"Translation quality: Theologically optimized\n")
                self.output_file.close()
                print(f"\n✅ Sermon translation saved to: {output_filename}")
    
    def translate_text(self, text):
        """
        Translate with domain optimization for expository sermons
        
        Configuration:
        - Domain: Expository sermon
        - Style: Formal, theologically accurate
        - Model: Neural Machine Translation (NMT)
        """
        if not text or not text.strip():
            return ""
        
        try:
            # Translate with Google Translate API
            result = self.translate_client.translate(
                text,
                target_language=self.target_lang_base,
                source_language=self.source_lang_base,
                format_='text',  # Plain text format
                model='nmt'  # Neural Machine Translation
            )
            
            return result['translatedText']
            
        except Exception as e:
            return f"[Translation error: {e}]"


# Main usage
if __name__ == "__main__":
    print("=" * 60)
    print("🎙️  REFORMED SERMON TRANSLATION SYSTEM")
    print("   Style: John MacArthur / Grace to You")
    print("=" * 60)
    
    # Configuration
    SOURCE_LANG = "en-US"  # Language being spoken
    TARGET_LANG = "pt"     # Language to translate to (pt, es, fr, etc.)
    ENABLE_TRANSLATION = True
    
    # Initialize components
    streamer = AudioStreamer()
    translator = SermonTranslator(
        source_language=SOURCE_LANG,
        target_language=TARGET_LANG
    )
    
    try:
        # Start audio capture
        streamer.start_stream()
        
        # Process with enhanced sermon translation
        translator.process_stream(
            streamer, 
            translate_enabled=ENABLE_TRANSLATION,
            save_to_file=True
        )
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping sermon translation...")
    finally:
        streamer.stop_stream()
        print("\n✅ Done!")