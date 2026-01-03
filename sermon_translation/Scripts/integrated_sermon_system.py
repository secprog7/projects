
"""
Integrated Sermon Translation System with Live Subtitle Display

Combines:
- Live audio capture (USB)
- Speech-to-Text (Google Cloud)
- Translation (Google Translate)
- Real-time subtitle display (Tkinter)
"""

import pyaudio
import queue
import threading
from typing import Generator
from google.cloud import speech
from google.cloud import translate_v2 as translate
from google.oauth2 import service_account
from datetime import datetime
import os
import tkinter as tk
from tkinter import font
from collections import deque

# Set credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials/sermon-streaming.json'

# Audio parameters
RATE = 16000
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1


class SubtitleDisplay:
    """Real-time subtitle display for translations"""
    
    def __init__(self, max_lines=3, font_size=28, show_source=False):
        """
        Initialize subtitle display
        
        Args:
            max_lines: Number of lines to show (2-3 recommended)
            font_size: Font size (24-32 recommended)
            show_source: Show both source and translation
        """
        self.max_lines = max_lines
        self.font_size = font_size
        self.show_source = show_source
        self.text_queue = queue.Queue()
        self.is_running = False
        
        self.display_lines = deque(maxlen=max_lines)
        
        # Create window
        self.root = tk.Tk()
        self.root.title("Sermon Translation Display")
        self.root.configure(bg='black')
        
        # Window sizing and positioning
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        window_height = 250 if show_source else 200
        window_width = int(screen_width * 0.85)
        
        x_position = (screen_width - window_width) // 2
        y_position = screen_height - window_height - 80
        
        self.root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
        self.root.attributes('-topmost', True)
        
        # Main frame
        main_frame = tk.Frame(self.root, bg='black')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Fonts
        self.display_font = font.Font(family="Arial", size=self.font_size, weight="bold")
        self.source_font = font.Font(family="Arial", size=self.font_size - 6)
        
        if show_source:
            # Dual language mode
            self.source_label = tk.Label(
                main_frame,
                text="",
                font=self.source_font,
                fg='lightgray',
                bg='black',
                justify='center',
                wraplength=window_width - 40
            )
            self.source_label.pack(pady=5)
            
            self.target_label = tk.Label(
                main_frame,
                text="",
                font=self.display_font,
                fg='white',
                bg='black',
                justify='center',
                wraplength=window_width - 40
            )
            self.target_label.pack(pady=5)
            
            self.source_lines = deque(maxlen=max_lines)
        else:
            # Single language mode
            self.text_label = tk.Label(
                main_frame,
                text="",
                font=self.display_font,
                fg='white',
                bg='black',
                justify='center',
                wraplength=window_width - 40,
                anchor='center'
            )
            self.text_label.pack(expand=True)
        
        # Language indicator
        self.lang_label = tk.Label(
            self.root,
            text="",
            font=('Arial', 10),
            fg='gray',
            bg='black'
        )
        self.lang_label.pack(side=tk.BOTTOM, pady=5)
        
        # Control buttons
        control_frame = tk.Frame(self.root, bg='black')
        control_frame.pack(side=tk.BOTTOM, pady=5)
        
        tk.Button(control_frame, text="Clear", command=self.clear_display,
                  bg='gray20', fg='white', font=('Arial', 10)).pack(side=tk.LEFT, padx=5)
        
        tk.Label(control_frame, text="Font:", bg='black', fg='white',
                 font=('Arial', 10)).pack(side=tk.LEFT, padx=5)
        
        tk.Button(control_frame, text="-", command=self.decrease_font,
                  bg='gray20', fg='white', font=('Arial', 10), width=3).pack(side=tk.LEFT, padx=2)
        
        tk.Button(control_frame, text="+", command=self.increase_font,
                  bg='gray20', fg='white', font=('Arial', 10), width=3).pack(side=tk.LEFT, padx=2)
        
        # Start processing
        self.is_running = True
        self.update_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.update_thread.start()
    
    def set_language(self, source_lang, target_lang):
        """Set language indicator"""
        self.lang_label.config(text=f"{source_lang} → {target_lang}")
    
    def add_text(self, source_text="", target_text=""):
        """Add text to display"""
        if target_text and target_text.strip():
            self.text_queue.put((source_text, target_text))
    
    def _process_queue(self):
        """Process incoming text"""
        while self.is_running:
            try:
                source, target = self.text_queue.get(timeout=0.1)
                self._update_display(source, target)
            except queue.Empty:
                continue
    
    def _update_display(self, source_text, target_text):
        """Update display with new text"""
        if self.show_source:
            self.source_lines.append(source_text)
            self.display_lines.append(target_text)
            
            source_display = "\n".join(self.source_lines)
            target_display = "\n".join(self.display_lines)
            
            self.root.after(0, lambda: self.source_label.config(text=source_display))
            self.root.after(0, lambda: self.target_label.config(text=target_display))
        else:
            self.display_lines.append(target_text)
            display_text = "\n".join(self.display_lines)
            self.root.after(0, lambda: self.text_label.config(text=display_text))
    
    def clear_display(self):
        """Clear display"""
        self.display_lines.clear()
        if self.show_source:
            self.source_lines.clear()
            self.source_label.config(text="")
            self.target_label.config(text="")
        else:
            self.text_label.config(text="")
    
    def increase_font(self):
        """Increase font size"""
        self.font_size = min(self.font_size + 2, 48)
        self.display_font.configure(size=self.font_size)
        if self.show_source:
            self.source_font.configure(size=self.font_size - 6)
    
    def decrease_font(self):
        """Decrease font size"""
        self.font_size = max(self.font_size - 2, 16)
        self.display_font.configure(size=self.font_size)
        if self.show_source:
            self.source_font.configure(size=self.font_size - 6)
    
    def run(self):
        """Start display"""
        self.root.mainloop()
    
    def stop(self):
        """Stop display"""
        self.is_running = False
        self.root.quit()


class AudioStreamer:
    """Captures audio from USB interface"""
    
    def __init__(self, device_index=None):
        self.audio = pyaudio.PyAudio()
        self.device_index = device_index or self._find_usb_device()
        self.audio_queue = queue.Queue()
        self.is_recording = False
        
    def _find_usb_device(self):
        """Find USB Audio Interface"""
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
        if self.is_recording:
            self.audio_queue.put(in_data)
        return (in_data, pyaudio.paContinue)
    
    def start_stream(self):
        """Start audio capture"""
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
    
    def audio_generator(self) -> Generator[bytes, None, None]:
        """Generate audio chunks"""
        while self.is_recording:
            try:
                chunk = self.audio_queue.get(timeout=1)
                yield chunk
            except queue.Empty:
                continue


class IntegratedSermonSystem:
    """
    Complete integrated system:
    Audio → STT → Translation → Live Display
    """
    
    # Theological terms for STT recognition
    SERMON_CONTEXT_HINTS = [
        "expository sermon", "verse by verse", "Biblical exposition",
        "Reformed theology", "let us turn to", "open your Bibles",
        "the text says", "the passage teaches", "justification by faith",
        "grace", "salvation", "redemption", "Scripture", "Gospel"
    ]
    
    def __init__(self, source_language="en-US", target_language="pt", 
                 show_both_languages=False, save_to_file=True):
        """
        Initialize integrated system
        
        Args:
            source_language: Source language code (e.g., "en-US")
            target_language: Target language code (e.g., "pt", "es")
            show_both_languages: Show source + translation
            save_to_file: Save to file in addition to display
        """
        # Initialize credentials
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 
                                    'credentials/sermon-streaming.json')
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        
        self.speech_client = speech.SpeechClient(credentials=credentials)
        self.translate_client = translate.Client(credentials=credentials)
        
        self.source_language = source_language
        self.target_language = target_language
        self.save_to_file = save_to_file
        self.output_file = None
        
        # Extract base language codes
        self.source_lang_base = source_language.split('-')[0]
        self.target_lang_base = target_language.split('-')[0] if '-' in target_language else target_language
        
        # Initialize display
        self.display = SubtitleDisplay(
            max_lines=3,
            font_size=28,
            show_source=show_both_languages
        )
        self.display.set_language(source_language, target_language.upper())
        
        # Initialize audio streamer
        self.audio_streamer = AudioStreamer()
        
        print(f"\n🔧 Integrated Sermon Translation System")
        print(f"   Domain: Expository Sermon (Reformed)")
        print(f"   Source: {source_language}")
        print(f"   Target: {target_language}")
        print(f"   Display: {'Dual Language' if show_both_languages else 'Translation Only'}")
    
    def translate_text(self, text):
        """Translate text"""
        if not text or not text.strip():
            return ""
        
        try:
            result = self.translate_client.translate(
                text,
                target_language=self.target_lang_base,
                source_language=self.source_lang_base,
                format_='text',
                model='nmt'
            )
            return result['translatedText']
        except Exception as e:
            return f"[Translation error: {e}]"
    
    def start(self):
        """Start the complete integrated system"""
        
        # Create output file if saving
        if self.save_to_file:
            os.makedirs("results", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"results/sermon_translation_{timestamp}.txt"
            self.output_file = open(output_filename, 'w', encoding='utf-8')
            
            # Write header
            self.output_file.write("SERMON TRANSLATION SESSION\n")
            self.output_file.write("="*60 + "\n")
            self.output_file.write(f"Date: {datetime.now()}\n")
            self.output_file.write(f"Domain: Expository Sermon (Reformed)\n")
            self.output_file.write(f"Source: {self.source_language}\n")
            self.output_file.write(f"Target: {self.target_language}\n")
            self.output_file.write("="*60 + "\n\n")
            self.output_file.flush()
            
            print(f"\n💾 Saving to: {output_filename}")
        
        # Start audio streaming in separate thread
        audio_thread = threading.Thread(target=self._audio_processing_thread, daemon=True)
        audio_thread.start()
        
        print("\n🎬 System started!")
        print("   - Audio capture running")
        print("   - Translation active")
        print("   - Display showing")
        print("\nPress Ctrl+C in terminal or close display window to stop.\n")
        
        # Run display (blocks until window closed)
        try:
            self.display.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
    
    def _audio_processing_thread(self):
        """Process audio in background thread"""
        
        # Configure STT with sermon optimization
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=self.source_language,
            enable_automatic_punctuation=True,
            use_enhanced=True,
            model="latest_long",
            speech_contexts=[
                speech.SpeechContext(
                    phrases=self.SERMON_CONTEXT_HINTS,
                    boost=15
                )
            ],
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=True,
            single_utterance=False  # Keep listening continuously
        )
        
        # Start audio capture
        self.audio_streamer.start_stream()
        
        segment_count = 0
        
        # Restart streaming if timeout occurs
        while self.display.is_running:
            try:
                # Create request generator
                def request_generator():
                    for chunk in self.audio_streamer.audio_generator():
                        if not self.display.is_running:
                            break
                        yield speech.StreamingRecognizeRequest(audio_content=chunk)
                
                print(f"\n🎧 Starting speech recognition stream...")
                
                responses = self.speech_client.streaming_recognize(
                    streaming_config,
                    request_generator()
                )
                
                for response in responses:
                    if not self.display.is_running:
                        break
                        
                    for result in response.results:
                        transcript = result.alternatives[0].transcript
                        
                        if result.is_final:
                            segment_count += 1
                            timestamp_str = datetime.now().strftime("%H:%M:%S")
                            
                            # Display English in console
                            print(f"📝 [{timestamp_str}] EN: {transcript}")
                            
                            # Translate immediately
                            translation = self.translate_text(transcript)
                            print(f"🌐 [{timestamp_str}] {self.target_language.upper()}: {translation}")
                            
                            # Send to display
                            self.display.add_text(
                                source_text=transcript,
                                target_text=translation
                            )
                            
                            # Save to file
                            if self.output_file:
                                self.output_file.write(f"[{timestamp_str}] Segment {segment_count}\n")
                                self.output_file.write(f"English: {transcript}\n")
                                self.output_file.write(f"{self.target_language.upper()}: {translation}\n")
                                self.output_file.write("-" * 60 + "\n\n")
                                self.output_file.flush()
                            
                            print("-" * 60)
                        else:
                            # Show interim in console only
                            print(f"💭 {transcript}", end='\r')
            
            except Exception as e:
                error_msg = str(e)
                if "Audio Timeout" in error_msg or "400" in error_msg:
                    print(f"\n⚠️  Stream timeout - restarting recognition...")
                    # Wait a moment and restart
                    import time
                    time.sleep(1)
                    continue  # Restart the streaming loop
                else:
                    print(f"\n❌ Error: {e}")
                    break
    
    def stop(self):
        """Stop the system"""
        print("\n⏹️  Stopping system...")
        
        self.audio_streamer.stop_stream()
        self.display.stop()
        
        if self.output_file:
            self.output_file.write("\n" + "="*60 + "\n")
            self.output_file.write(f"Session ended: {datetime.now()}\n")
            self.output_file.close()
        
        print("✅ System stopped.")


# Main entry point
if __name__ == "__main__":
    print("=" * 60)
    print("🎙️  INTEGRATED SERMON TRANSLATION SYSTEM")
    print("   Audio → STT → Translation → Live Display")
    print("=" * 60)
    
    # Language configuration
    print("\n📋 LANGUAGE CONFIGURATION")
    print("-" * 60)
    
    # Source language selection
    print("\nSOURCE LANGUAGE (audio input from microphone):")
    print("1. English (US)")
    print("2. English (UK)")
    print("3. Portuguese (Brazil)")
    print("4. Portuguese (Portugal)")
    print("5. Spanish (Spain)")
    print("6. Spanish (Latin America)")
    print("7. French")
    print("8. Other (enter code)")
    
    source_choice = input("\nSelect source language (1-8): ").strip()
    
    source_languages = {
        "1": "en-US",
        "2": "en-GB",
        "3": "pt-BR",
        "4": "pt-PT",
        "5": "es-ES",
        "6": "es-MX",
        "7": "fr-FR",
    }
    
    if source_choice == "8":
        SOURCE_LANG = input("Enter source language code (e.g., en-US, pt-BR): ").strip()
    else:
        SOURCE_LANG = source_languages.get(source_choice, "en-US")
    
    print(f"✓ Source language: {SOURCE_LANG}")
    
    # Target language selection
    print("\nTARGET LANGUAGE (translation output to display):")
    print("1. Portuguese (Brazil)")
    print("2. Portuguese (Portugal)")
    print("3. Spanish (Spain)")
    print("4. Spanish (Latin America)")
    print("5. French")
    print("6. English (US)")
    print("7. English (UK)")
    print("8. German")
    print("9. Italian")
    print("10. Korean")
    print("11. Chinese (Simplified)")
    print("12. Japanese")
    print("13. Other (enter code)")
    
    target_choice = input("\nSelect target language (1-13): ").strip()
    
    target_languages = {
        "1": "pt-BR",
        "2": "pt-PT",
        "3": "es-ES",
        "4": "es-MX",
        "5": "fr-FR",
        "6": "en-US",
        "7": "en-GB",
        "8": "de",
        "9": "it",
        "10": "ko",
        "11": "zh-CN",
        "12": "ja",
    }
    
    if target_choice == "13":
        TARGET_LANG = input("Enter target language code (e.g., pt, es, fr): ").strip()
    else:
        TARGET_LANG = target_languages.get(target_choice, "pt-BR")
    
    print(f"✓ Target language: {TARGET_LANG}")
    
    # Display mode
    print("\nDISPLAY MODE:")
    print("1. Translation only (target language)")
    print("2. Dual language (source + translation)")
    
    choice = input("\nSelect display mode (1 or 2): ").strip()
    show_both = (choice == "2")
    
    # Confirmation
    print("\n" + "=" * 60)
    print("CONFIGURATION SUMMARY")
    print("=" * 60)
    print(f"Source Language (Audio In): {SOURCE_LANG}")
    print(f"Target Language (Display): {TARGET_LANG}")
    print(f"Display Mode: {'Dual Language' if show_both else 'Translation Only'}")
    print(f"File Saving: Enabled")
    print("=" * 60)
    
    confirm = input("\nProceed with this configuration? (Y/n): ").strip().lower()
    
    if confirm and confirm != 'y':
        print("Configuration cancelled.")
        exit()
    
    # Create and start system
    system = IntegratedSermonSystem(
        source_language=SOURCE_LANG,
        target_language=TARGET_LANG,
        show_both_languages=show_both,
        save_to_file=True
    )
    
    try:
        system.start()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        system.stop()