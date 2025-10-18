import pyaudio
import queue
import threading
from typing import Generator
from google.cloud import speech
from google.cloud import translate_v2 as translate

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
        """Find USB Audio Interface device (0.2.C)"""
        print("\nAvailable audio devices:")
        for i in range(self.audio.get_device_count()):
            info = self.audio.get_device_info_by_index(i)
            print(f"  [{i}] {info['name']}")
            if "USB" in info['name'] or "0.2.C" in info['name']:
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


class SpeechToTextTranslator:
    """Handles Google Cloud Speech-to-Text and Translation"""
    
    def __init__(self, source_language="en-US", target_language="es"):
        """
        Initialize STT and Translation clients
        
        Args:
            source_language: Language code for speech (e.g., "en-US", "es-ES", "fr-FR")
            target_language: Target language code for translation (e.g., "es", "fr", "de")
        """
        self.speech_client = speech.SpeechClient()
        self.translate_client = translate.Client()
        self.source_language = source_language
        self.target_language = target_language
        
    def process_stream(self, audio_streamer, translate_enabled=True):
        """
        Process audio stream with STT and optional translation
        
        Args:
            audio_streamer: AudioStreamer instance
            translate_enabled: Whether to translate transcriptions
        """
        # Configure STT
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=self.source_language,
            enable_automatic_punctuation=True,
            model="default",  # Use "latest_long" for better accuracy
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True  # Get partial results while speaking
        )
        
        # Create request generator
        def request_generator():
            for chunk in audio_streamer.audio_generator():
                yield speech.StreamingRecognizeRequest(audio_content=chunk)
        
        # Stream to Google Cloud Speech-to-Text
        print(f"\n🎧 Listening in {self.source_language}...")
        if translate_enabled:
            print(f"🌐 Translating to {self.target_language}...\n")
        
        try:
            responses = self.speech_client.streaming_recognize(
                streaming_config, 
                request_generator()
            )
            
            for response in responses:
                for result in response.results:
                    transcript = result.alternatives[0].transcript
                    
                    if result.is_final:
                        # Final transcription
                        print(f"📝 Original: {transcript}")
                        
                        # Translate if enabled
                        if translate_enabled:
                            translation = self.translate_text(transcript)
                            print(f"🌍 Translated: {translation}")
                        print("-" * 60)
                    else:
                        # Interim result (partial transcription)
                        print(f"💭 {transcript}", end='\r')
                        
        except Exception as e:
            print(f"\n❌ Error: {e}")
    
    def translate_text(self, text):
        """
        Translate text using Google Cloud Translate
        
        Args:
            text: Text to translate
            
        Returns:
            Translated text
        """
        try:
            result = self.translate_client.translate(
                text,
                target_language=self.target_language,
                source_language=self.source_language.split('-')[0]  # Extract base language
            )
            return result['translatedText']
        except Exception as e:
            return f"[Translation error: {e}]"


# Main usage
if __name__ == "__main__":
    print("=" * 60)
    print("🎙️  USB Audio → Speech-to-Text → Translation")
    print("=" * 60)
    
    # Configuration
    SOURCE_LANG = "en-US"  # Language being spoken
    TARGET_LANG = "es"     # Language to translate to
    ENABLE_TRANSLATION = True
    
    # Supported language codes:
    # Speech: "en-US", "es-ES", "fr-FR", "de-DE", "ja-JP", "zh-CN", etc.
    # Translation: "es", "fr", "de", "ja", "zh", "ar", "hi", etc.
    
    # Initialize components
    streamer = AudioStreamer()
    translator = SpeechToTextTranslator(
        source_language=SOURCE_LANG,
        target_language=TARGET_LANG
    )
    
    try:
        # Start audio capture
        streamer.start_stream()
        
        # Process audio with STT and translation
        translator.process_stream(streamer, translate_enabled=ENABLE_TRANSLATION)
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping...")
    finally:
        streamer.stop_stream()
        print("\n✅ Done!")