"""
Multi-Language Integrated Sermon Translation System

Features:
- 1 input language → 1-4 output languages
- Dual-language display (side-by-side)
- Combined file output with all translations
- Number-based configuration (no typing)
- Redo/Cancel options
"""

import pyaudio
import queue
import threading
from typing import Generator, List
from google.cloud import speech
from google.cloud import translate_v2 as translate
from google.oauth2 import service_account
from datetime import datetime
import os
import warnings
import tkinter as tk
from tkinter import font
from collections import deque

# Suppress warnings
os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GRPC_TRACE'] = ''
warnings.filterwarnings('ignore')

# Set credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials/sermon-streaming.json'

# Audio parameters
RATE = 16000
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1

# Language mappings
INPUT_LANGUAGES = {
    "1": ("en-US", "English (US)"),
    "2": ("en-GB", "English (UK)"),
    "3": ("pt-BR", "Portuguese (Brazil)"),
    "4": ("pt-PT", "Portuguese (Portugal)"),
    "5": ("es-ES", "Spanish (Spain)"),
    "6": ("es-MX", "Spanish (Latin America)"),
    "7": ("fr-FR", "French"),
    "8": ("de-DE", "German"),
    "9": ("it-IT", "Italian"),
    "10": ("ko-KR", "Korean"),
    "11": ("zh-CN", "Chinese (Mandarin)"),
    "12": ("ja-JP", "Japanese"),
}

OUTPUT_LANGUAGES = {
    "1": ("es-ES", "Spanish (Spain)"),
    "2": ("es-MX", "Spanish (Latin America)"),
    "3": ("pt-BR", "Portuguese (Brazil)"),
    "4": ("pt-PT", "Portuguese (Portugal)"),
    "5": ("fr-FR", "French"),
    "6": ("de-DE", "German"),
    "7": ("it-IT", "Italian"),
    "8": ("en-US", "English (US)"),
    "9": ("en-GB", "English (UK)"),
    "10": ("ko-KR", "Korean"),
    "11": ("zh-CN", "Chinese (Simplified)"),
    "12": ("zh-TW", "Chinese (Traditional)"),
    "13": ("ja-JP", "Japanese"),
    "14": ("ar", "Arabic"),
    "15": ("hi", "Hindi"),
    "16": ("ru", "Russian"),
}


class DualLanguageDisplay:
    """Display showing 2 languages side-by-side with pause/resume control"""
    
    def __init__(self, language1_name, language2_name, font_size=24):
        self.font_size = font_size
        self.text_queue = queue.Queue()
        self.is_running = False
        self.is_paused = False  # Pause state
        
        self.lang1_lines = deque(maxlen=3)
        self.lang2_lines = deque(maxlen=3)
        
        # Create window
        self.root = tk.Tk()
        self.root.title("Sermon Translation Display")
        self.root.configure(bg='black')
        
        # Window sizing
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        window_height = 450
        window_width = int(screen_width * 0.85)
        
        x_position = (screen_width - window_width) // 2
        y_position = screen_height - window_height - 80
        
        self.root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
        self.root.attributes('-topmost', True)
        
        # Fonts
        self.display_font = font.Font(family="Arial", size=self.font_size, weight="bold")
        self.label_font = font.Font(family="Arial", size=14, weight="bold")
        self.status_font = font.Font(family="Arial", size=12, weight="bold")
        
        # Status bar (top)
        self.status_bar = tk.Label(
            self.root,
            text="🟢 ACTIVE - Ctrl+Shift+P to pause",
            font=self.status_font,
            fg='white',
            bg='green',
            pady=8
        )
        self.status_bar.pack(fill=tk.X)
        
        # Main container
        main_frame = tk.Frame(self.root, bg='black')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Language 1 section (top)
        lang1_frame = tk.Frame(main_frame, bg='black')
        lang1_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.lang1_label_header = tk.Label(
            lang1_frame,
            text=language1_name.upper(),
            font=self.label_font,
            fg='yellow',
            bg='black'
        )
        self.lang1_label_header.pack()
        
        self.lang1_text = tk.Label(
            lang1_frame,
            text="",
            font=self.display_font,
            fg='white',
            bg='black',
            justify='center',
            wraplength=window_width - 40
        )
        self.lang1_text.pack(expand=True)
        
        # Separator
        separator = tk.Frame(main_frame, bg='gray', height=2)
        separator.pack(fill=tk.X, pady=5)
        
        # Language 2 section (bottom)
        lang2_frame = tk.Frame(main_frame, bg='black')
        lang2_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        self.lang2_label_header = tk.Label(
            lang2_frame,
            text=language2_name.upper(),
            font=self.label_font,
            fg='cyan',
            bg='black'
        )
        self.lang2_label_header.pack()
        
        self.lang2_text = tk.Label(
            lang2_frame,
            text="",
            font=self.display_font,
            fg='white',
            bg='black',
            justify='center',
            wraplength=window_width - 40
        )
        self.lang2_text.pack(expand=True)
        
        # Control info bar (bottom)
        control_info = tk.Label(
            self.root,
            text="Controls: [Ctrl+Shift+P] Pause  [Ctrl+Shift+R] Resume  [Ctrl+Shift+S] Stop",
            font=('Arial', 9),
            fg='lightgray',
            bg='black',
            pady=5
        )
        control_info.pack(fill=tk.X)
        
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
    
    def set_paused(self, paused):
        """Update pause state and display"""
        self.is_paused = paused
        if paused:
            self.status_bar.config(
                text="🟡 PAUSED - Ctrl+Shift+R to resume",
                bg='orange'
            )
        else:
            self.status_bar.config(
                text="🟢 ACTIVE - Ctrl+Shift+P to pause",
                bg='green'
            )
    
    def add_translation(self, lang1_text, lang2_text):
        """Add translation pair to display"""
        if lang1_text and lang2_text:
            self.text_queue.put((lang1_text, lang2_text))
    
    def _process_queue(self):
        """Process incoming translations"""
        while self.is_running:
            try:
                lang1, lang2 = self.text_queue.get(timeout=0.1)
                self._update_display(lang1, lang2)
            except queue.Empty:
                continue
    
    def _update_display(self, lang1_text, lang2_text):
        """Update both language displays"""
        self.lang1_lines.append(lang1_text)
        self.lang2_lines.append(lang2_text)
        
        lang1_display = "\n".join(self.lang1_lines)
        lang2_display = "\n".join(self.lang2_lines)
        
        self.root.after(0, lambda: self.lang1_text.config(text=lang1_display))
        self.root.after(0, lambda: self.lang2_text.config(text=lang2_display))
    
    def clear_display(self):
        """Clear both displays"""
        self.lang1_lines.clear()
        self.lang2_lines.clear()
        self.lang1_text.config(text="")
        self.lang2_text.config(text="")
    
    def increase_font(self):
        """Increase font size"""
        self.font_size = min(self.font_size + 2, 48)
        self.display_font.configure(size=self.font_size)
    
    def decrease_font(self):
        """Decrease font size"""
        self.font_size = max(self.font_size - 2, 16)
        self.display_font.configure(size=self.font_size)
    
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


class MultiLanguageSermonSystem:
    """Complete multi-language translation system with pause/resume"""
    
    SERMON_CONTEXT_HINTS = [
        "expository sermon", "verse by verse", "Biblical exposition",
        "Reformed theology", "let us turn to", "open your Bibles",
        "grace", "salvation", "redemption", "Scripture", "Gospel"
    ]
    
    def __init__(self, source_language, target_languages, display_languages):
        """
        Initialize system
        
        Args:
            source_language: (code, name) tuple for input
            target_languages: List of (code, name) tuples for outputs
            display_languages: List of 2 (code, name) tuples for display
        """
        # Initialize credentials
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 
                                    'credentials/sermon-streaming.json')
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        
        self.speech_client = speech.SpeechClient(credentials=credentials)
        self.translate_client = translate.Client(credentials=credentials)
        
        self.source_language = source_language
        self.target_languages = target_languages
        self.display_languages = display_languages
        self.output_file = None
        
        # Pause/resume control
        self.is_paused = True  # Start paused
        self.pause_start_time = None
        self.total_pause_time = 0
        self.pause_count = 0
        self.active_start_time = None
        self.total_active_time = 0
        
        # Initialize display
        self.display = DualLanguageDisplay(
            display_languages[0][1],
            display_languages[1][1],
            font_size=28
        )
        
        # Set up keyboard bindings
        self.display.root.bind('<Control-Shift-P>', self._pause_translation)
        self.display.root.bind('<Control-Shift-p>', self._pause_translation)
        self.display.root.bind('<Control-Shift-R>', self._resume_translation)
        self.display.root.bind('<Control-Shift-r>', self._resume_translation)
        self.display.root.bind('<Control-Shift-S>', self._stop_system)
        self.display.root.bind('<Control-Shift-s>', self._stop_system)
        
        # Initialize audio
        self.audio_streamer = AudioStreamer()
        
        print(f"\n🔧 Multi-Language Sermon Translation System")
        print(f"   Input: {source_language[1]}")
        print(f"   Outputs: {', '.join([lang[1] for lang in target_languages])}")
        print(f"   Display: {display_languages[0][1]} + {display_languages[1][1]}")
        print(f"\n⏯️  PAUSE/RESUME CONTROLS:")
        print(f"   Ctrl+Shift+P - Pause translation")
        print(f"   Ctrl+Shift+R - Resume translation")
        print(f"   Ctrl+Shift+S - Stop system")
    
    def _pause_translation(self, event=None):
        """Pause translation (Ctrl+Shift+P)"""
        if not self.is_paused:
            self.is_paused = True
            self.pause_start_time = datetime.now()
            self.pause_count += 1
            
            # Update display
            self.display.set_paused(True)
            
            # Calculate active time
            if self.active_start_time:
                self.total_active_time += (datetime.now() - self.active_start_time).total_seconds()
            
            # Log to console
            timestamp_str = datetime.now().strftime("%H:%M:%S")
            print(f"\n⏸️  [{timestamp_str}] TRANSLATION PAUSED")
            print(f"   (Press Ctrl+Shift+R to resume)")
            
            # Log to file
            if self.output_file:
                self.output_file.write(f"\n[{timestamp_str}] ⏸️  === TRANSLATION PAUSED ===\n")
                self.output_file.write(f"Duration active: {self._format_duration(self.total_active_time)}\n\n")
                self.output_file.flush()
    
    def _resume_translation(self, event=None):
        """Resume translation (Ctrl+Shift+R)"""
        if self.is_paused:
            self.is_paused = False
            self.active_start_time = datetime.now()
            
            # Update display
            self.display.set_paused(False)
            
            # Calculate pause time
            if self.pause_start_time:
                pause_duration = (datetime.now() - self.pause_start_time).total_seconds()
                self.total_pause_time += pause_duration
            
            # Log to console
            timestamp_str = datetime.now().strftime("%H:%M:%S")
            print(f"\n▶️  [{timestamp_str}] TRANSLATION RESUMED")
            if self.pause_start_time:
                print(f"   Pause duration: {self._format_duration(pause_duration)}")
            
            # Log to file
            if self.output_file:
                self.output_file.write(f"[{timestamp_str}] ▶️  === TRANSLATION RESUMED ===\n")
                if self.pause_start_time:
                    self.output_file.write(f"Pause duration: {self._format_duration(pause_duration)}\n")
                self.output_file.write("\n")
                self.output_file.flush()
    
    def _stop_system(self, event=None):
        """Stop system completely (Ctrl+Shift+S)"""
        print("\n🛑 Stopping system via keyboard command...")
        self.display.stop()
    
    def _format_duration(self, seconds):
        """Format duration in seconds to readable format"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    
    def translate_to_multiple(self, text):
        """Translate text to all target languages"""
        translations = {}
        
        source_base = self.source_language[0].split('-')[0]
        
        for lang_code, lang_name in self.target_languages:
            target_base = lang_code.split('-')[0] if '-' in lang_code else lang_code
            
            try:
                result = self.translate_client.translate(
                    text,
                    target_language=target_base,
                    source_language=source_base,
                    format_='text',
                    model='nmt'
                )
                translations[lang_name] = result['translatedText']
            except Exception as e:
                translations[lang_name] = f"[Error: {e}]"
        
        return translations
    
    def start(self):
        """Start the complete system"""
        
        # Create output file
        os.makedirs("results", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"results/sermon_multilang_{timestamp}.txt"
        self.output_file = open(output_filename, 'w', encoding='utf-8')
        
        # Write header
        self.output_file.write("MULTI-LANGUAGE SERMON TRANSLATION\n")
        self.output_file.write("="*70 + "\n")
        self.output_file.write(f"Date: {datetime.now()}\n")
        self.output_file.write(f"Input Language: {self.source_language[1]}\n")
        self.output_file.write(f"Output Languages: {', '.join([l[1] for l in self.target_languages])}\n")
        self.output_file.write("="*70 + "\n\n")
        self.output_file.write(f"[{datetime.now().strftime('%H:%M:%S')}] 🟡 System ready (PAUSED)\n")
        self.output_file.write("   Press Ctrl+Shift+R to start translation\n\n")
        self.output_file.flush()
        
        print(f"\n💾 Saving to: {output_filename}")
        
        # Start audio processing thread
        audio_thread = threading.Thread(target=self._audio_processing_thread, daemon=True)
        audio_thread.start()
        
        print("\n🎬 System started!")
        print("   - Audio capture ready")
        print("   - Multi-language translation configured")
        print("   - Display showing")
        print(f"\n🟡 STATUS: PAUSED - Press Ctrl+Shift+R to start translation")
        print("\nControls:")
        print("   Ctrl+Shift+R - Start/Resume translation")
        print("   Ctrl+Shift+P - Pause translation")
        print("   Ctrl+Shift+S - Stop system\n")
        
        # Set initial paused state
        self.display.set_paused(True)
        
        # Run display
        try:
            self.display.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
    
    def _audio_processing_thread(self):
        """Process audio in background"""
        
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=self.source_language[0],
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
            single_utterance=False
        )
        
        self.audio_streamer.start_stream()
        
        segment_count = 0
        
        while self.display.is_running:
            # Wait if paused
            if self.is_paused:
                import time
                time.sleep(0.5)
                continue
            
            try:
                def request_generator():
                    for chunk in self.audio_streamer.audio_generator():
                        if not self.display.is_running or self.is_paused:
                            break
                        yield speech.StreamingRecognizeRequest(audio_content=chunk)
                
                print(f"\n🎧 Starting speech recognition stream...")
                
                responses = self.speech_client.streaming_recognize(
                    streaming_config,
                    request_generator()
                )
                
                for response in responses:
                    if not self.display.is_running or self.is_paused:
                        break
                        
                    for result in response.results:
                        transcript = result.alternatives[0].transcript
                        
                        if result.is_final:
                            segment_count += 1
                            timestamp_str = datetime.now().strftime("%H:%M:%S")
                            
                            print(f"📝 [{timestamp_str}] {self.source_language[1]}: {transcript}")
                            
                            # Translate to all languages
                            translations = self.translate_to_multiple(transcript)
                            
                            # Display translations in console
                            for lang_name, translation in translations.items():
                                print(f"🌐 [{timestamp_str}] {lang_name}: {translation}")
                            
                            # Update display (first 2 languages)
                            display_lang1 = translations[self.display_languages[0][1]]
                            display_lang2 = translations[self.display_languages[1][1]]
                            self.display.add_translation(display_lang1, display_lang2)
                            
                            # Save to file (all languages)
                            if self.output_file:
                                self.output_file.write(f"[{timestamp_str}] Segment {segment_count}\n")
                                self.output_file.write("─" * 70 + "\n")
                                self.output_file.write(f"{self.source_language[1]:<20} {transcript}\n")
                                for lang_name, translation in translations.items():
                                    self.output_file.write(f"{lang_name:<20} {translation}\n")
                                self.output_file.write("─" * 70 + "\n\n")
                                self.output_file.flush()
                            
                            print("-" * 70)
                        else:
                            print(f"💭 {transcript}", end='\r')
            
            except Exception as e:
                error_msg = str(e)
                if "Audio Timeout" in error_msg or "400" in error_msg:
                    if not self.is_paused:
                        print(f"\n⚠️  Stream timeout - restarting recognition...")
                    import time
                    time.sleep(1)
                    continue
                else:
                    print(f"\n❌ Error: {e}")
                    break
    
    def stop(self):
        """Stop the system"""
        print("\n⏹️  Stopping system...")
        
        # Calculate final times
        if self.active_start_time and not self.is_paused:
            self.total_active_time += (datetime.now() - self.active_start_time).total_seconds()
        
        self.audio_streamer.stop_stream()
        self.display.stop()
        
        if self.output_file:
            self.output_file.write("\n" + "="*70 + "\n")
            self.output_file.write("SESSION SUMMARY\n")
            self.output_file.write("="*70 + "\n")
            self.output_file.write(f"Session ended: {datetime.now()}\n")
            self.output_file.write(f"Total active time: {self._format_duration(self.total_active_time)}\n")
            self.output_file.write(f"Total pause time: {self._format_duration(self.total_pause_time)}\n")
            self.output_file.write(f"Pause count: {self.pause_count}\n")
            self.output_file.write(f"Languages: {', '.join([l[1] for l in self.target_languages])}\n")
            self.output_file.write("="*70 + "\n")
            self.output_file.close()
        
        print("✅ System stopped.")
        print(f"\n📊 Session Statistics:")
        print(f"   Active time: {self._format_duration(self.total_active_time)}")
        print(f"   Pause time: {self._format_duration(self.total_pause_time)}")
        print(f"   Pauses: {self.pause_count} times")


def configure_system():
    """Interactive configuration with redo/cancel options"""
    
    while True:  # Configuration loop for redo
        print("\n" + "="*70)
        print("    SERMON TRANSLATION SYSTEM - CONFIGURATION")
        print("="*70)
        
        # Step 1: Input language
        print("\nSTEP 1: SELECT INPUT LANGUAGE (audio from microphone)")
        print("-" * 70)
        for num, (code, name) in INPUT_LANGUAGES.items():
            print(f"{num:>2}. {name}")
        
        while True:
            choice = input("\nEnter number (1-12): ").strip()
            if choice in INPUT_LANGUAGES:
                source_language = INPUT_LANGUAGES[choice]
                print(f"✓ Input language: {source_language[1]}")
                break
            print("❌ Invalid choice. Try again.")
        
        # Step 2: Number of output languages
        print("\nSTEP 2: HOW MANY OUTPUT LANGUAGES?")
        print("-" * 70)
        while True:
            num_outputs = input("Enter number of output languages (1-4): ").strip()
            if num_outputs in ['1', '2', '3', '4']:
                num_outputs = int(num_outputs)
                print(f"✓ Will translate to {num_outputs} language(s)")
                break
            print("❌ Invalid choice. Enter 1, 2, 3, or 4.")
        
        # Step 3: Select output languages
        print("\nSTEP 3: SELECT OUTPUT LANGUAGES")
        print("-" * 70)
        print("Available languages:")
        for num, (code, name) in OUTPUT_LANGUAGES.items():
            print(f"{num:>2}. {name}")
        
        target_languages = []
        for i in range(num_outputs):
            while True:
                choice = input(f"\nSelect output language #{i+1} (1-16): ").strip()
                if choice in OUTPUT_LANGUAGES:
                    lang = OUTPUT_LANGUAGES[choice]
                    if lang not in target_languages:
                        target_languages.append(lang)
                        print(f"✓ Language {i+1}: {lang[1]}")
                        break
                    else:
                        print("❌ Language already selected. Choose a different one.")
                else:
                    print("❌ Invalid choice. Try again.")
        
        # Step 4: Display configuration
        print("\nSTEP 4: DISPLAY CONFIGURATION")
        print("-" * 70)
        
        if num_outputs == 1:
            display_languages = [target_languages[0], target_languages[0]]
            print(f"Display mode: Single language ({target_languages[0][1]})")
        elif num_outputs == 2:
            display_languages = target_languages[:2]
            print(f"Display mode: Dual view (side-by-side)")
            print(f"[{display_languages[0][1]} shown in top half]")
            print(f"[{display_languages[1][1]} shown in bottom half]")
        else:
            print(f"You selected {num_outputs} languages. Which 2 should be displayed?")
            for i, lang in enumerate(target_languages, 1):
                print(f"{i}. {lang[1]}")
            
            display_languages = []
            for i in range(2):
                while True:
                    choice = input(f"Select display language #{i+1} (1-{num_outputs}): ").strip()
                    try:
                        idx = int(choice) - 1
                        if 0 <= idx < num_outputs:
                            lang = target_languages[idx]
                            if lang not in display_languages:
                                display_languages.append(lang)
                                print(f"✓ Display {i+1}: {lang[1]}")
                                break
                            else:
                                print("❌ Already selected. Choose different language.")
                        else:
                            print(f"❌ Enter number 1-{num_outputs}.")
                    except ValueError:
                        print("❌ Enter a valid number.")
        
        # Summary
        print("\n" + "="*70)
        print("    CONFIGURATION SUMMARY")
        print("="*70)
        print(f"Input Language:     {source_language[1]}")
        print(f"Output Languages:   {', '.join([l[1] for l in target_languages])}")
        print(f"Display Mode:       {display_languages[0][1]} + {display_languages[1][1]}")
        print(f"File Output:        Combined file with all translations")
        print(f"Save Location:      results/")
        print("="*70)
        
        print("\nOPTIONS:")
        print("1. Start system with this configuration")
        print("2. Redo configuration (start over)")
        print("3. Cancel (exit program)")
        
        while True:
            choice = input("\nEnter choice (1-3): ").strip()
            if choice == "1":
                print("\n✓ Starting translation system...")
                return source_language, target_languages, display_languages
            elif choice == "2":
                print("\n✓ Restarting configuration...\n")
                break  # Break inner loop to restart outer loop
            elif choice == "3":
                print("\n✓ Configuration cancelled. Exiting...")
                exit(0)
            else:
                print("❌ Invalid choice. Enter 1, 2, or 3.")
        
        # If we broke from choice == 2, continue outer while loop


# Main entry point
if __name__ == "__main__":
    print("="*70)
    print("🎙️  MULTI-LANGUAGE SERMON TRANSLATION SYSTEM")
    print("   Audio → STT → Multi-Language Translation → Display")
    print("="*70)
    
    # Configure system
    source_lang, target_langs, display_langs = configure_system()
    
    # Create and start system
    system = MultiLanguageSermonSystem(
        source_language=source_lang,
        target_languages=target_langs,
        display_languages=display_langs
    )
    
    try:
        system.start()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        system.stop()