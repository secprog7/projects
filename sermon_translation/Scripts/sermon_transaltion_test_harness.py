"""
Multi-Language Sermon Translation System - TEST HARNESS

This is a testing version with instrumentation for measuring and comparing
different latency reduction strategies.

TEST MODES:
  0. Baseline - Current behavior (no changes)
  1. Fast Display - Reduced display times, no fades
  2. Smart Queue - Catch-up mode when behind
  3. Latency Control - Hard max 20sec delay limit
  4. Interim Results - Show non-final results immediately

OUTPUTS:
  - Real-time latency indicator on display
  - CSV log files with timestamp data
  - Summary reports after each test
"""

import pyaudio
import queue
import threading
from typing import Generator, List, Dict, Optional
from google.cloud import speech
from google.cloud import translate_v2 as translate
from google.oauth2 import service_account
from datetime import datetime
import os
import warnings
import tkinter as tk
from tkinter import font
import json
import csv
import time
from dataclasses import dataclass, field
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

# =============================================================================
# TEST MODE CONFIGURATIONS
# =============================================================================

TEST_MODES = {
    0: {
        "name": "Baseline",
        "description": "Current behavior - no modifications",
        "reading_speed": 240,
        "min_display_time": 3,
        "fade_duration": 1.0,
        "buffer_time": 1,
        "use_interim_results": False,
        "max_latency": None,  # No limit
        "catchup_enabled": False,
        "catchup_threshold": None,
    },
    1: {
        "name": "Fast Display",
        "description": "Reduced display times, no fade transitions",
        "reading_speed": 320,  # Faster reading speed
        "min_display_time": 2,  # Shorter minimum
        "fade_duration": 0.0,  # No fades
        "buffer_time": 0.5,
        "use_interim_results": False,
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
    },
    2: {
        "name": "Smart Queue",
        "description": "Catch-up mode when queue builds up",
        "reading_speed": 240,
        "min_display_time": 3,
        "fade_duration": 1.0,
        "buffer_time": 1,
        "use_interim_results": False,
        "max_latency": None,
        "catchup_enabled": True,
        "catchup_threshold": 2,  # Items in queue to trigger catchup
        "catchup_reading_speed": 400,
        "catchup_min_display": 1.5,
        "catchup_fade_duration": 0.2,
    },
    3: {
        "name": "Latency Control",
        "description": "Hard limit of 20 seconds max delay",
        "reading_speed": 240,
        "min_display_time": 3,
        "fade_duration": 1.0,
        "buffer_time": 1,
        "use_interim_results": False,
        "max_latency": 20,  # Seconds - hard limit
        "catchup_enabled": True,
        "catchup_threshold": 2,
        "catchup_reading_speed": 400,
        "catchup_min_display": 1.5,
        "catchup_fade_duration": 0.2,
        "skip_when_exceeded": True,  # Skip old items if over max latency
    },
    4: {
        "name": "Interim Results",
        "description": "Show non-final results immediately (text may update)",
        "reading_speed": 240,
        "min_display_time": 3,
        "fade_duration": 0.5,
        "buffer_time": 1,
        "use_interim_results": True,
        "interim_style": "italic",  # Visual indicator for interim
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
    },
}

# Language mappings (same as original)
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


# =============================================================================
# DATA CLASSES FOR TRACKING
# =============================================================================

@dataclass
class SegmentData:
    """Tracks timing data for a single translation segment"""
    segment_id: int
    text_original: str
    text_translated: Dict[str, str]
    word_count: int
    timestamp_spoken: datetime  # When speech was captured
    timestamp_recognized: datetime  # When STT returned final result
    timestamp_translated: datetime  # When translation completed
    timestamp_queued: datetime  # When added to display queue
    timestamp_displayed: datetime = None  # When shown on screen
    timestamp_cleared: datetime = None  # When removed from screen
    is_interim: bool = False
    was_skipped: bool = False
    queue_depth_at_queue: int = 0
    queue_depth_at_display: int = 0
    
    @property
    def latency_total(self) -> float:
        """Total latency from speech to display"""
        if self.timestamp_displayed:
            return (self.timestamp_displayed - self.timestamp_spoken).total_seconds()
        return None
    
    @property
    def latency_recognition(self) -> float:
        """Time for speech recognition"""
        return (self.timestamp_recognized - self.timestamp_spoken).total_seconds()
    
    @property
    def latency_translation(self) -> float:
        """Time for translation"""
        return (self.timestamp_translated - self.timestamp_recognized).total_seconds()
    
    @property
    def latency_queue_wait(self) -> float:
        """Time waiting in display queue"""
        if self.timestamp_displayed:
            return (self.timestamp_displayed - self.timestamp_queued).total_seconds()
        return None
    
    @property
    def display_duration(self) -> float:
        """How long text was displayed"""
        if self.timestamp_cleared and self.timestamp_displayed:
            return (self.timestamp_cleared - self.timestamp_displayed).total_seconds()
        return None


@dataclass
class TestSession:
    """Tracks data for entire test session"""
    test_mode: int
    mode_name: str
    mode_config: dict
    start_time: datetime
    end_time: datetime = None
    segments: List[SegmentData] = field(default_factory=list)
    skipped_segments: int = 0
    catchup_activations: int = 0
    interim_updates: int = 0
    
    def add_segment(self, segment: SegmentData):
        self.segments.append(segment)
    
    @property
    def duration_seconds(self) -> float:
        if self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return (datetime.now() - self.start_time).total_seconds()
    
    @property
    def avg_latency(self) -> float:
        latencies = [s.latency_total for s in self.segments if s.latency_total]
        return sum(latencies) / len(latencies) if latencies else 0
    
    @property
    def max_latency(self) -> float:
        latencies = [s.latency_total for s in self.segments if s.latency_total]
        return max(latencies) if latencies else 0
    
    @property
    def min_latency(self) -> float:
        latencies = [s.latency_total for s in self.segments if s.latency_total]
        return min(latencies) if latencies else 0


# =============================================================================
# TEST HARNESS DISPLAY (with latency indicator)
# =============================================================================

class TestHarnessDisplay:
    """Display with real-time latency indicator and test mode info"""
    
    def __init__(self, language1_name, language2_name, test_mode_config, font_size=24):
        self.font_size = font_size
        self.config = test_mode_config
        self.text_queue = queue.Queue()
        self.is_running = False
        self.is_paused = False
        self.in_catchup_mode = False
        
        # Current text being displayed
        self.current_lang1 = ""
        self.current_lang2 = ""
        self.current_is_interim = False
        self.display_start_time = None
        
        # Latency tracking for display
        self.current_latency = 0.0
        self.queue_depth = 0
        self.segments_displayed = 0
        self.segments_skipped = 0
        
        # Create window
        self.root = tk.Tk()
        self.root.title(f"TEST MODE: {test_mode_config['name']}")
        self.root.configure(bg='black')
        
        # Window sizing
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        window_height = 500  # Slightly taller for test info
        window_width = int(screen_width * 0.85)
        
        x_position = (screen_width - window_width) // 2
        y_position = screen_height - window_height - 80
        
        self.root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
        self.root.attributes('-topmost', True)
        
        # Fonts
        self.display_font = font.Font(family="Arial", size=self.font_size, weight="bold")
        self.display_font_italic = font.Font(family="Arial", size=self.font_size, weight="bold", slant="italic")
        self.label_font = font.Font(family="Arial", size=14, weight="bold")
        self.status_font = font.Font(family="Arial", size=12, weight="bold")
        self.metrics_font = font.Font(family="Consolas", size=11, weight="bold")
        
        # === TEST INFO BAR (top) ===
        test_info_frame = tk.Frame(self.root, bg='#1a1a2e')
        test_info_frame.pack(fill=tk.X)
        
        self.test_mode_label = tk.Label(
            test_info_frame,
            text=f"🧪 TEST MODE {list(TEST_MODES.keys())[list(TEST_MODES.values()).index(test_mode_config)]}: {test_mode_config['name']}",
            font=self.status_font,
            fg='#00ff88',
            bg='#1a1a2e',
            pady=5
        )
        self.test_mode_label.pack(side=tk.LEFT, padx=10)
        
        self.test_desc_label = tk.Label(
            test_info_frame,
            text=test_mode_config['description'],
            font=('Arial', 10),
            fg='#888888',
            bg='#1a1a2e',
            pady=5
        )
        self.test_desc_label.pack(side=tk.LEFT, padx=10)
        
        # === LATENCY METRICS BAR ===
        metrics_frame = tk.Frame(self.root, bg='#0f0f23')
        metrics_frame.pack(fill=tk.X)
        
        # Latency indicator
        self.latency_label = tk.Label(
            metrics_frame,
            text="⏱️ Latency: 0.0s",
            font=self.metrics_font,
            fg='#00ff00',
            bg='#0f0f23',
            pady=8,
            padx=15
        )
        self.latency_label.pack(side=tk.LEFT)
        
        # Queue depth indicator
        self.queue_label = tk.Label(
            metrics_frame,
            text="📋 Queue: 0",
            font=self.metrics_font,
            fg='#ffff00',
            bg='#0f0f23',
            pady=8,
            padx=15
        )
        self.queue_label.pack(side=tk.LEFT)
        
        # Segments counter
        self.segments_label = tk.Label(
            metrics_frame,
            text="📊 Displayed: 0 | Skipped: 0",
            font=self.metrics_font,
            fg='#aaaaaa',
            bg='#0f0f23',
            pady=8,
            padx=15
        )
        self.segments_label.pack(side=tk.LEFT)
        
        # Catchup mode indicator
        self.catchup_label = tk.Label(
            metrics_frame,
            text="",
            font=self.metrics_font,
            fg='#ff6600',
            bg='#0f0f23',
            pady=8,
            padx=15
        )
        self.catchup_label.pack(side=tk.RIGHT)
        
        # === STATUS BAR ===
        self.status_bar = tk.Label(
            self.root,
            text="🟢 ACTIVE - Ctrl+Shift+P to pause",
            font=self.status_font,
            fg='white',
            bg='green',
            pady=8
        )
        self.status_bar.pack(fill=tk.X)
        
        # === MAIN CONTENT ===
        main_frame = tk.Frame(self.root, bg='black')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Language 1 section
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
            wraplength=window_width - 100
        )
        self.lang1_text.pack(expand=True)
        
        # Separator
        separator = tk.Frame(main_frame, bg='gray', height=2)
        separator.pack(fill=tk.X, pady=5)
        
        # Language 2 section
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
            wraplength=window_width - 100
        )
        self.lang2_text.pack(expand=True)
        
        # === CONTROL BAR ===
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
        
        # Start processing thread
        self.is_running = True
        self.update_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.update_thread.start()
        
        # Start metrics update thread
        self.metrics_thread = threading.Thread(target=self._update_metrics_loop, daemon=True)
        self.metrics_thread.start()
    
    def _get_display_times(self):
        """Get current display timing settings (may vary in catchup mode)"""
        if self.in_catchup_mode and self.config.get('catchup_enabled'):
            return {
                'reading_speed': self.config.get('catchup_reading_speed', 400),
                'min_display_time': self.config.get('catchup_min_display', 1.5),
                'fade_duration': self.config.get('catchup_fade_duration', 0.2),
                'buffer_time': 0.3
            }
        return {
            'reading_speed': self.config['reading_speed'],
            'min_display_time': self.config['min_display_time'],
            'fade_duration': self.config['fade_duration'],
            'buffer_time': self.config.get('buffer_time', 1)
        }
    
    def _calculate_display_time(self, text):
        """Calculate display time based on current mode"""
        times = self._get_display_times()
        words = len(text.split())
        reading_time = (words / times['reading_speed']) * 60
        total_time = max(
            reading_time + times['buffer_time'],
            times['min_display_time']
        )
        return total_time
    
    def update_latency(self, latency_seconds):
        """Update the latency display"""
        self.current_latency = latency_seconds
    
    def update_queue_depth(self, depth):
        """Update queue depth display"""
        self.queue_depth = depth
        
        # Check if we should enter/exit catchup mode
        if self.config.get('catchup_enabled'):
            threshold = self.config.get('catchup_threshold', 2)
            if depth >= threshold and not self.in_catchup_mode:
                self.in_catchup_mode = True
            elif depth < threshold and self.in_catchup_mode:
                self.in_catchup_mode = False
    
    def _update_metrics_loop(self):
        """Update metrics display periodically"""
        while self.is_running:
            try:
                # Update latency color based on value
                if self.current_latency < 10:
                    latency_color = '#00ff00'  # Green
                elif self.current_latency < 15:
                    latency_color = '#ffff00'  # Yellow
                elif self.current_latency < 20:
                    latency_color = '#ff8800'  # Orange
                else:
                    latency_color = '#ff0000'  # Red
                
                self.root.after(0, lambda c=latency_color: self.latency_label.config(
                    text=f"⏱️ Latency: {self.current_latency:.1f}s",
                    fg=c
                ))
                
                # Update queue depth color
                if self.queue_depth <= 1:
                    queue_color = '#00ff00'
                elif self.queue_depth <= 3:
                    queue_color = '#ffff00'
                else:
                    queue_color = '#ff0000'
                
                self.root.after(0, lambda c=queue_color: self.queue_label.config(
                    text=f"📋 Queue: {self.queue_depth}",
                    fg=c
                ))
                
                # Update segments counter
                self.root.after(0, lambda: self.segments_label.config(
                    text=f"📊 Displayed: {self.segments_displayed} | Skipped: {self.segments_skipped}"
                ))
                
                # Update catchup indicator
                if self.in_catchup_mode:
                    self.root.after(0, lambda: self.catchup_label.config(
                        text="⚡ CATCH-UP MODE"
                    ))
                else:
                    self.root.after(0, lambda: self.catchup_label.config(text=""))
                
            except Exception as e:
                pass
            
            time.sleep(0.2)
    
    def set_paused(self, paused):
        """Update pause state"""
        self.is_paused = paused
        if paused:
            self.status_bar.config(text="🟡 PAUSED - Ctrl+Shift+R to resume", bg='orange')
        else:
            self.status_bar.config(text="🟢 ACTIVE - Ctrl+Shift+P to pause", bg='green')
    
    def add_translation(self, lang1_text, lang2_text, segment_data: SegmentData, is_interim=False):
        """Add translation to queue with tracking data"""
        if lang1_text and lang2_text:
            self.text_queue.put((lang1_text, lang2_text, segment_data, is_interim))
            self.update_queue_depth(self.text_queue.qsize())
    
    def _process_queue(self):
        """Process translations with timing"""
        while self.is_running:
            try:
                lang1, lang2, segment_data, is_interim = self.text_queue.get(timeout=0.1)
                self.update_queue_depth(self.text_queue.qsize())
                
                # Check max latency limit
                if self.config.get('max_latency') and segment_data:
                    current_latency = (datetime.now() - segment_data.timestamp_spoken).total_seconds()
                    if current_latency > self.config['max_latency'] and self.config.get('skip_when_exceeded'):
                        # Skip this segment - too old
                        segment_data.was_skipped = True
                        self.segments_skipped += 1
                        print(f"⏭️  Skipping segment (latency {current_latency:.1f}s > {self.config['max_latency']}s)")
                        continue
                
                # Update segment queue depth
                if segment_data:
                    segment_data.queue_depth_at_display = self.text_queue.qsize()
                
                # Fade out current if exists
                if self.current_lang1:
                    elapsed = (datetime.now() - self.display_start_time).total_seconds()
                    required_time = self._calculate_display_time(self.current_lang1)
                    
                    if elapsed < required_time:
                        time.sleep(required_time - elapsed)
                    
                    self._fade_out()
                
                # Display new text
                self._fade_in(lang1, lang2, is_interim)
                
                # Record display timestamp
                if segment_data:
                    segment_data.timestamp_displayed = datetime.now()
                    self.update_latency(segment_data.latency_total or 0)
                    self.segments_displayed += 1
                
            except queue.Empty:
                continue
    
    def _fade_out(self):
        """Fade out current text"""
        times = self._get_display_times()
        fade_duration = times['fade_duration']
        
        if fade_duration <= 0:
            self.root.after(0, lambda: self.lang1_text.config(text=""))
            self.root.after(0, lambda: self.lang2_text.config(text=""))
            return
        
        fade_steps = 10
        fade_delay = fade_duration / fade_steps
        
        for step in range(fade_steps, -1, -1):
            if not self.is_running:
                break
            alpha = step / fade_steps
            brightness = int(255 * alpha)
            color = f'#{brightness:02x}{brightness:02x}{brightness:02x}'
            
            self.root.after(0, lambda c=color: self.lang1_text.config(fg=c))
            self.root.after(0, lambda c=color: self.lang2_text.config(fg=c))
            time.sleep(fade_delay)
    
    def _fade_in(self, lang1_text, lang2_text, is_interim=False):
        """Fade in new text"""
        self.current_lang1 = lang1_text
        self.current_lang2 = lang2_text
        self.current_is_interim = is_interim
        self.display_start_time = datetime.now()
        
        times = self._get_display_times()
        fade_duration = times['fade_duration']
        
        # Set font style based on interim status
        if is_interim and self.config.get('use_interim_results'):
            text_font = self.display_font_italic
            base_color = '#aaaaff'  # Slight blue tint for interim
        else:
            text_font = self.display_font
            base_color = '#ffffff'
        
        if fade_duration <= 0:
            self.root.after(0, lambda: self.lang1_text.config(text=lang1_text, fg=base_color, font=text_font))
            self.root.after(0, lambda: self.lang2_text.config(text=lang2_text, fg=base_color, font=text_font))
            return
        
        fade_steps = 10
        fade_delay = fade_duration / fade_steps
        
        for step in range(fade_steps + 1):
            if not self.is_running:
                break
            alpha = step / fade_steps
            brightness = int(255 * alpha)
            color = f'#{brightness:02x}{brightness:02x}{brightness:02x}'
            
            self.root.after(0, lambda t=lang1_text, c=color, f=text_font: self.lang1_text.config(text=t, fg=c, font=f))
            self.root.after(0, lambda t=lang2_text, c=color, f=text_font: self.lang2_text.config(text=t, fg=c, font=f))
            time.sleep(fade_delay)
    
    def clear_display(self):
        """Clear display"""
        self.current_lang1 = ""
        self.current_lang2 = ""
        self.lang1_text.config(text="")
        self.lang2_text.config(text="")
    
    def increase_font(self):
        self.font_size = min(self.font_size + 2, 48)
        self.display_font.configure(size=self.font_size)
        self.display_font_italic.configure(size=self.font_size)
    
    def decrease_font(self):
        self.font_size = max(self.font_size - 2, 16)
        self.display_font.configure(size=self.font_size)
        self.display_font_italic.configure(size=self.font_size)
    
    def run(self):
        self.root.mainloop()
    
    def stop(self):
        self.is_running = False
        self.root.quit()


# =============================================================================
# AUDIO STREAMER (same as original)
# =============================================================================

class AudioStreamer:
    """Captures audio from USB interface"""
    
    def __init__(self, device_index=None):
        self.audio = pyaudio.PyAudio()
        self.device_index = device_index or self._find_usb_device()
        self.audio_queue = queue.Queue()
        self.is_recording = False
        
    def _find_usb_device(self):
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
            self.audio_queue.put((in_data, datetime.now()))  # Include timestamp
        return (in_data, pyaudio.paContinue)
    
    def start_stream(self):
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
        self.is_recording = False
        if hasattr(self, 'stream'):
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()
    
    def audio_generator(self) -> Generator[tuple, None, None]:
        while self.is_recording:
            try:
                data, timestamp = self.audio_queue.get(timeout=1)
                yield data, timestamp
            except queue.Empty:
                continue


# =============================================================================
# TEST HARNESS MAIN SYSTEM
# =============================================================================

class TestHarnessSystem:
    """Main test harness system with full instrumentation"""
    
    SERMON_CONTEXT_HINTS = [
        "expository sermon", "verse by verse", "Biblical exposition",
        "Reformed theology", "let us turn to", "open your Bibles",
        "grace", "salvation", "redemption", "Scripture", "Gospel"
    ]
    
    def __init__(self, source_language, target_languages, display_languages, test_mode: int):
        # Credentials
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 
                                    'credentials/sermon-streaming.json')
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        
        self.speech_client = speech.SpeechClient(credentials=credentials)
        self.translate_client = translate.Client(credentials=credentials)
        
        self.source_language = source_language
        self.target_languages = target_languages
        self.display_languages = display_languages
        
        # Test mode configuration
        self.test_mode = test_mode
        self.test_config = TEST_MODES[test_mode]
        
        # Session tracking
        self.session = TestSession(
            test_mode=test_mode,
            mode_name=self.test_config['name'],
            mode_config=self.test_config,
            start_time=datetime.now()
        )
        
        self.segment_counter = 0
        self.output_file = None
        self.csv_file = None
        self.csv_writer = None
        
        # Pause control
        self.is_paused = True
        self.pause_start_time = None
        self.total_pause_time = 0
        self.active_start_time = None
        self.total_active_time = 0
        
        # Initialize display
        self.display = TestHarnessDisplay(
            display_languages[0][1],
            display_languages[1][1],
            self.test_config,
            font_size=28
        )
        
        # Keyboard bindings
        self.display.root.bind('<Control-Shift-P>', self._pause)
        self.display.root.bind('<Control-Shift-p>', self._pause)
        self.display.root.bind('<Control-Shift-R>', self._resume)
        self.display.root.bind('<Control-Shift-r>', self._resume)
        self.display.root.bind('<Control-Shift-S>', self._stop)
        self.display.root.bind('<Control-Shift-s>', self._stop)
        
        # Audio
        self.audio_streamer = AudioStreamer()
        
        # Track last audio timestamp for latency calculation
        self.last_audio_timestamp = None
        
        print(f"\n🧪 TEST HARNESS INITIALIZED")
        print(f"   Mode: {test_mode} - {self.test_config['name']}")
        print(f"   Description: {self.test_config['description']}")
        print(f"   Input: {source_language[1]}")
        print(f"   Outputs: {', '.join([l[1] for l in target_languages])}")
    
    def _pause(self, event=None):
        if not self.is_paused:
            self.is_paused = True
            self.pause_start_time = datetime.now()
            self.display.set_paused(True)
            
            if self.active_start_time:
                self.total_active_time += (datetime.now() - self.active_start_time).total_seconds()
            
            print(f"\n⏸️  [{datetime.now().strftime('%H:%M:%S')}] PAUSED")
    
    def _resume(self, event=None):
        if self.is_paused:
            self.is_paused = False
            self.active_start_time = datetime.now()
            self.display.set_paused(False)
            
            if self.pause_start_time:
                self.total_pause_time += (datetime.now() - self.pause_start_time).total_seconds()
            
            print(f"\n▶️  [{datetime.now().strftime('%H:%M:%S')}] RESUMED")
    
    def _stop(self, event=None):
        print("\n🛑 Stopping test...")
        self.display.stop()
    
    def translate_to_multiple(self, text):
        translations = {}
        source_base = self.source_language[0].split('-')[0]
        
        for lang_code, lang_name in self.target_languages:
            target_base = lang_code.split('-')[0] if '-' in lang_code else lang_code
            try:
                result = self.translate_client.translate(
                    text, target_language=target_base,
                    source_language=source_base, format_='text', model='nmt'
                )
                translations[lang_name] = result['translatedText']
            except Exception as e:
                translations[lang_name] = f"[Error: {e}]"
        
        return translations
    
    def _write_csv_row(self, segment: SegmentData):
        """Write segment data to CSV"""
        if self.csv_writer:
            self.csv_writer.writerow({
                'segment_id': segment.segment_id,
                'timestamp_spoken': segment.timestamp_spoken.isoformat(),
                'timestamp_displayed': segment.timestamp_displayed.isoformat() if segment.timestamp_displayed else '',
                'latency_total': f"{segment.latency_total:.2f}" if segment.latency_total else '',
                'latency_recognition': f"{segment.latency_recognition:.2f}",
                'latency_translation': f"{segment.latency_translation:.2f}",
                'latency_queue_wait': f"{segment.latency_queue_wait:.2f}" if segment.latency_queue_wait else '',
                'word_count': segment.word_count,
                'queue_depth': segment.queue_depth_at_queue,
                'is_interim': segment.is_interim,
                'was_skipped': segment.was_skipped,
                'text_original': segment.text_original[:100]  # Truncate for CSV
            })
            self.csv_file.flush()
    
    def start(self):
        """Start the test"""
        # Create output directory
        os.makedirs("test_results", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_name = self.test_config['name'].lower().replace(' ', '_')
        
        # CSV file for raw data
        csv_filename = f"test_results/{mode_name}_{timestamp}.csv"
        self.csv_file = open(csv_filename, 'w', newline='', encoding='utf-8')
        self.csv_writer = csv.DictWriter(self.csv_file, fieldnames=[
            'segment_id', 'timestamp_spoken', 'timestamp_displayed',
            'latency_total', 'latency_recognition', 'latency_translation',
            'latency_queue_wait', 'word_count', 'queue_depth',
            'is_interim', 'was_skipped', 'text_original'
        ])
        self.csv_writer.writeheader()
        
        # Text log file
        log_filename = f"test_results/{mode_name}_{timestamp}_log.txt"
        self.output_file = open(log_filename, 'w', encoding='utf-8')
        self.output_file.write(f"TEST HARNESS LOG\n")
        self.output_file.write(f"{'='*70}\n")
        self.output_file.write(f"Mode: {self.test_mode} - {self.test_config['name']}\n")
        self.output_file.write(f"Description: {self.test_config['description']}\n")
        self.output_file.write(f"Started: {datetime.now()}\n")
        self.output_file.write(f"Configuration: {json.dumps(self.test_config, indent=2)}\n")
        self.output_file.write(f"{'='*70}\n\n")
        self.output_file.flush()
        
        print(f"\n💾 Saving to:")
        print(f"   CSV: {csv_filename}")
        print(f"   Log: {log_filename}")
        
        # Start audio thread
        audio_thread = threading.Thread(target=self._audio_processing, daemon=True)
        audio_thread.start()
        
        print(f"\n🎬 Test started!")
        print(f"   Press Ctrl+Shift+R to begin")
        print(f"   Press Ctrl+Shift+S to stop\n")
        
        self.display.set_paused(True)
        
        try:
            self.display.run()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
    
    def _audio_processing(self):
        """Audio processing with full instrumentation"""
        
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=self.source_language[0],
            enable_automatic_punctuation=True,
            use_enhanced=True,
            model="latest_long",
            speech_contexts=[
                speech.SpeechContext(phrases=self.SERMON_CONTEXT_HINTS, boost=15)
            ],
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=self.test_config.get('use_interim_results', False),
            single_utterance=False
        )
        
        self.audio_streamer.start_stream()
        
        while self.display.is_running:
            if self.is_paused:
                time.sleep(0.5)
                continue
            
            try:
                # Track when we started capturing this audio batch
                batch_start_time = datetime.now()
                
                def request_generator():
                    for chunk, timestamp in self.audio_streamer.audio_generator():
                        if not self.display.is_running or self.is_paused:
                            break
                        self.last_audio_timestamp = timestamp
                        yield speech.StreamingRecognizeRequest(audio_content=chunk)
                
                responses = self.speech_client.streaming_recognize(
                    streaming_config, request_generator()
                )
                
                for response in responses:
                    if not self.display.is_running or self.is_paused:
                        break
                    
                    for result in response.results:
                        transcript = result.alternatives[0].transcript
                        is_final = result.is_final
                        
                        # Use interim results if configured
                        if not is_final and not self.test_config.get('use_interim_results'):
                            print(f"💭 {transcript}", end='\r')
                            continue
                        
                        # Create segment data
                        self.segment_counter += 1
                        timestamp_spoken = self.last_audio_timestamp or batch_start_time
                        timestamp_recognized = datetime.now()
                        
                        # Translate
                        translations = self.translate_to_multiple(transcript)
                        timestamp_translated = datetime.now()
                        
                        segment = SegmentData(
                            segment_id=self.segment_counter,
                            text_original=transcript,
                            text_translated=translations,
                            word_count=len(transcript.split()),
                            timestamp_spoken=timestamp_spoken,
                            timestamp_recognized=timestamp_recognized,
                            timestamp_translated=timestamp_translated,
                            timestamp_queued=datetime.now(),
                            is_interim=not is_final,
                            queue_depth_at_queue=self.display.text_queue.qsize()
                        )
                        
                        # Log to console
                        status = "📝" if is_final else "💭"
                        print(f"{status} [{datetime.now().strftime('%H:%M:%S')}] {transcript}")
                        
                        for lang_name, translation in translations.items():
                            print(f"   🌐 {lang_name}: {translation}")
                        
                        # Add to display queue
                        display_lang1 = translations[self.display_languages[0][1]]
                        display_lang2 = translations[self.display_languages[1][1]]
                        self.display.add_translation(display_lang1, display_lang2, segment, not is_final)
                        
                        # Write to CSV
                        self._write_csv_row(segment)
                        
                        # Add to session
                        self.session.add_segment(segment)
                        
                        # Log to file
                        if self.output_file:
                            self.output_file.write(f"[{datetime.now().strftime('%H:%M:%S')}] Segment {segment.segment_id}\n")
                            self.output_file.write(f"  Latency: {segment.latency_recognition:.2f}s (recog) + {segment.latency_translation:.2f}s (trans)\n")
                            self.output_file.write(f"  Queue depth: {segment.queue_depth_at_queue}\n")
                            self.output_file.write(f"  Text: {transcript}\n\n")
                            self.output_file.flush()
                        
                        print("-" * 50)
            
            except Exception as e:
                error_msg = str(e)
                if "Audio Timeout" in error_msg or "400" in error_msg:
                    if not self.is_paused:
                        print(f"\n⚠️  Stream timeout - restarting...")
                    time.sleep(1)
                    continue
                else:
                    print(f"\n❌ Error: {e}")
                    break
    
    def stop(self):
        """Stop and generate summary"""
        print("\n⏹️  Stopping test...")
        
        self.session.end_time = datetime.now()
        
        if self.active_start_time and not self.is_paused:
            self.total_active_time += (datetime.now() - self.active_start_time).total_seconds()
        
        self.audio_streamer.stop_stream()
        self.display.stop()
        
        # Generate summary
        self._generate_summary()
        
        if self.csv_file:
            self.csv_file.close()
        if self.output_file:
            self.output_file.close()
        
        print("✅ Test complete!")
    
    def _generate_summary(self):
        """Generate test summary report"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_name = self.test_config['name'].lower().replace(' ', '_')
        summary_filename = f"test_results/{mode_name}_{timestamp}_summary.txt"
        
        # Calculate statistics
        latencies = [s.latency_total for s in self.session.segments if s.latency_total and not s.was_skipped]
        
        # Calculate latency trend (first half vs second half)
        if len(latencies) > 4:
            first_half = latencies[:len(latencies)//2]
            second_half = latencies[len(latencies)//2:]
            first_avg = sum(first_half) / len(first_half)
            second_avg = sum(second_half) / len(second_half)
            trend_per_segment = (second_avg - first_avg) / (len(latencies) // 2)
            # Estimate trend per minute
            if self.session.duration_seconds > 0:
                segments_per_minute = len(self.session.segments) / (self.session.duration_seconds / 60)
                trend_per_minute = trend_per_segment * segments_per_minute
            else:
                trend_per_minute = 0
        else:
            trend_per_minute = 0
            first_avg = 0
            second_avg = 0
        
        summary = f"""
{'='*70}
TEST SUMMARY: {self.test_config['name']}
{'='*70}

TEST CONFIGURATION
------------------
Mode: {self.test_mode} - {self.test_config['name']}
Description: {self.test_config['description']}
Reading Speed: {self.test_config['reading_speed']} wpm
Min Display Time: {self.test_config['min_display_time']}s
Fade Duration: {self.test_config['fade_duration']}s
Use Interim Results: {self.test_config.get('use_interim_results', False)}
Max Latency Limit: {self.test_config.get('max_latency', 'None')}
Catchup Enabled: {self.test_config.get('catchup_enabled', False)}

TIMING STATISTICS
-----------------
Test Duration: {self.session.duration_seconds/60:.1f} minutes
Active Time: {self.total_active_time/60:.1f} minutes
Pause Time: {self.total_pause_time/60:.1f} minutes

SEGMENT STATISTICS
------------------
Total Segments: {len(self.session.segments)}
Displayed: {self.display.segments_displayed}
Skipped: {self.display.segments_skipped}
Segments/Minute: {len(self.session.segments)/(self.session.duration_seconds/60):.1f}

LATENCY STATISTICS
------------------
Average Latency: {self.session.avg_latency:.2f} seconds
Maximum Latency: {self.session.max_latency:.2f} seconds
Minimum Latency: {self.session.min_latency:.2f} seconds

LATENCY TREND
-------------
First Half Average: {first_avg:.2f} seconds
Second Half Average: {second_avg:.2f} seconds
Trend: {'+' if trend_per_minute > 0 else ''}{trend_per_minute:.2f} sec/minute {'(INCREASING ⚠️)' if trend_per_minute > 0.5 else '(STABLE ✓)' if abs(trend_per_minute) < 0.5 else '(DECREASING ✓)'}

LATENCY DISTRIBUTION
--------------------
Under 5 seconds:  {len([l for l in latencies if l < 5]):3d} ({100*len([l for l in latencies if l < 5])/len(latencies) if latencies else 0:.1f}%)
5-10 seconds:     {len([l for l in latencies if 5 <= l < 10]):3d} ({100*len([l for l in latencies if 5 <= l < 10])/len(latencies) if latencies else 0:.1f}%)
10-15 seconds:    {len([l for l in latencies if 10 <= l < 15]):3d} ({100*len([l for l in latencies if 10 <= l < 15])/len(latencies) if latencies else 0:.1f}%)
15-20 seconds:    {len([l for l in latencies if 15 <= l < 20]):3d} ({100*len([l for l in latencies if 15 <= l < 20])/len(latencies) if latencies else 0:.1f}%)
Over 20 seconds:  {len([l for l in latencies if l >= 20]):3d} ({100*len([l for l in latencies if l >= 20])/len(latencies) if latencies else 0:.1f}%) {'⚠️ EXCEEDS TARGET' if len([l for l in latencies if l >= 20]) > 0 else '✓'}

{'='*70}
"""
        
        # Write to file
        with open(summary_filename, 'w', encoding='utf-8') as f:
            f.write(summary)
        
        # Print to console
        print(summary)
        print(f"\n📊 Summary saved to: {summary_filename}")


# =============================================================================
# CONFIGURATION MENUS
# =============================================================================

def select_test_mode():
    """Interactive test mode selection"""
    print("\n" + "="*70)
    print("    SERMON TRANSLATION - TEST MODE SELECTION")
    print("="*70)
    
    for mode_num, config in TEST_MODES.items():
        print(f"\n  {mode_num}. {config['name']}")
        print(f"     {config['description']}")
        print(f"     Settings: {config['reading_speed']} wpm, {config['min_display_time']}s min, {config['fade_duration']}s fade")
        if config.get('use_interim_results'):
            print(f"     ⚡ Shows interim results (text may change)")
        if config.get('max_latency'):
            print(f"     ⏱️ Max latency: {config['max_latency']}s")
        if config.get('catchup_enabled'):
            print(f"     🏃 Catchup mode enabled (threshold: {config.get('catchup_threshold')} items)")
    
    print("\n" + "-"*70)
    print("  L. View last test results")
    print("  C. Compare all test results")
    print("  Q. Quit")
    print("-"*70)
    
    while True:
        choice = input("\nEnter choice (0-4, L, C, Q): ").strip().upper()
        
        if choice == 'Q':
            print("Exiting...")
            exit(0)
        elif choice == 'L':
            view_last_results()
            return select_test_mode()  # Return to menu
        elif choice == 'C':
            compare_all_results()
            return select_test_mode()  # Return to menu
        elif choice in ['0', '1', '2', '3', '4']:
            return int(choice)
        else:
            print("❌ Invalid choice. Try again.")


def view_last_results():
    """View the most recent test results"""
    results_dir = "test_results"
    if not os.path.exists(results_dir):
        print("\n⚠️  No test results found.")
        input("Press Enter to continue...")
        return
    
    # Find most recent summary file
    summary_files = [f for f in os.listdir(results_dir) if f.endswith('_summary.txt')]
    if not summary_files:
        print("\n⚠️  No summary files found.")
        input("Press Enter to continue...")
        return
    
    summary_files.sort(reverse=True)
    latest = os.path.join(results_dir, summary_files[0])
    
    print(f"\n📊 Latest results: {summary_files[0]}\n")
    with open(latest, 'r') as f:
        print(f.read())
    
    input("\nPress Enter to continue...")


def compare_all_results():
    """Compare results from all test modes"""
    results_dir = "test_results"
    if not os.path.exists(results_dir):
        print("\n⚠️  No test results found.")
        input("Press Enter to continue...")
        return
    
    # Find all summary files
    summary_files = [f for f in os.listdir(results_dir) if f.endswith('_summary.txt')]
    if not summary_files:
        print("\n⚠️  No summary files found.")
        input("Press Enter to continue...")
        return
    
    print("\n" + "="*70)
    print("    TEST RESULTS COMPARISON")
    print("="*70)
    
    # Parse summaries and display comparison table
    results = []
    for sf in summary_files:
        filepath = os.path.join(results_dir, sf)
        with open(filepath, 'r') as f:
            content = f.read()
            
            # Extract key metrics (simple parsing)
            mode_name = sf.split('_')[0].replace('_', ' ').title()
            
            # Try to extract values
            try:
                avg_lat = float(content.split('Average Latency:')[1].split('seconds')[0].strip())
                max_lat = float(content.split('Maximum Latency:')[1].split('seconds')[0].strip())
                segments = int(content.split('Total Segments:')[1].split('\n')[0].strip())
                over_20 = content.split('Over 20 seconds:')[1].split('(')[0].strip()
                
                results.append({
                    'file': sf,
                    'mode': mode_name,
                    'avg_latency': avg_lat,
                    'max_latency': max_lat,
                    'segments': segments,
                    'over_20': over_20
                })
            except:
                pass
    
    if results:
        print(f"\n{'Mode':<20} {'Avg Lat':>10} {'Max Lat':>10} {'Segments':>10} {'Over 20s':>10}")
        print("-" * 60)
        for r in results:
            print(f"{r['mode']:<20} {r['avg_latency']:>10.2f}s {r['max_latency']:>10.2f}s {r['segments']:>10} {r['over_20']:>10}")
    else:
        print("\nCould not parse summary files.")
    
    print("\n" + "-"*70)
    print("Individual summary files:")
    for sf in sorted(summary_files, reverse=True):
        print(f"  • {sf}")
    
    input("\nPress Enter to continue...")


def configure_languages():
    """Configure input/output languages (simplified for testing)"""
    print("\n" + "="*70)
    print("    LANGUAGE CONFIGURATION")
    print("="*70)
    
    # Input language
    print("\nSTEP 1: INPUT LANGUAGE")
    print("-" * 70)
    for num, (code, name) in INPUT_LANGUAGES.items():
        print(f"{num:>2}. {name}")
    
    while True:
        choice = input("\nEnter number (1-12): ").strip()
        if choice in INPUT_LANGUAGES:
            source_language = INPUT_LANGUAGES[choice]
            print(f"✓ Input: {source_language[1]}")
            break
        print("❌ Invalid choice.")
    
    # Output languages (simplified: pick 2 for display)
    print("\nSTEP 2: OUTPUT LANGUAGES (select 2 for display)")
    print("-" * 70)
    for num, (code, name) in OUTPUT_LANGUAGES.items():
        print(f"{num:>2}. {name}")
    
    target_languages = []
    for i in range(2):
        while True:
            choice = input(f"\nSelect output language #{i+1} (1-16): ").strip()
            if choice in OUTPUT_LANGUAGES:
                lang = OUTPUT_LANGUAGES[choice]
                if lang not in target_languages:
                    target_languages.append(lang)
                    print(f"✓ Language {i+1}: {lang[1]}")
                    break
                else:
                    print("❌ Already selected.")
            else:
                print("❌ Invalid choice.")
    
    return source_language, target_languages, target_languages


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("="*70)
    print("🧪 SERMON TRANSLATION SYSTEM - TEST HARNESS")
    print("   Instrumented version for latency testing and comparison")
    print("="*70)
    
    # Select test mode
    test_mode = select_test_mode()
    
    # Configure languages
    source_lang, target_langs, display_langs = configure_languages()
    
    # Confirm
    print("\n" + "="*70)
    print("    TEST CONFIGURATION")
    print("="*70)
    print(f"Test Mode: {test_mode} - {TEST_MODES[test_mode]['name']}")
    print(f"Input: {source_lang[1]}")
    print(f"Output: {', '.join([l[1] for l in target_langs])}")
    print("="*70)
    
    confirm = input("\nStart test? (Y/n): ").strip().lower()
    if confirm == 'n':
        print("Cancelled.")
        exit(0)
    
    # Create and run system
    system = TestHarnessSystem(
        source_language=source_lang,
        target_languages=target_langs,
        display_languages=display_langs,
        test_mode=test_mode
    )
    
    try:
        system.start()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        system.stop()