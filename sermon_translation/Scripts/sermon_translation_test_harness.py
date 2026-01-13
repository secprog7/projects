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

AUDIO INPUT:
  - Live microphone (USB/Focusrite)
  - Audio file (MP3, WAV) with real-time or accelerated playback

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
from datetime import datetime, timedelta
import os
import warnings
import tkinter as tk
from tkinter import font
from tkinter import filedialog
import json
import csv
import time
from dataclasses import dataclass, field
from collections import deque
import wave
import io
import subprocess
import tempfile
import shutil

# Check for ffmpeg availability
def check_ffmpeg():
    """Check if ffmpeg is available"""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'], 
            capture_output=True, 
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False

FFMPEG_AVAILABLE = check_ffmpeg()

if not FFMPEG_AVAILABLE:
    print("WARNING:  ffmpeg not found. MP3 support disabled.")
    print("   Install ffmpeg: https://ffmpeg.org/download.html")
    print("   Or use: winget install ffmpeg")

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
        "chunk_split_enabled": False,
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
        "chunk_split_enabled": False,
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
        "chunk_split_enabled": False,
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
        "chunk_split_enabled": False,
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
        "chunk_split_enabled": False,
    },
    5: {
        "name": "Optimized Speed",
        "description": "Balanced settings for ~5-7 sec latency without losing translations",
        "reading_speed": 280,  # Slightly faster (vs 240 baseline)
        "min_display_time": 2.5,  # Shorter minimum (vs 3)
        "fade_duration": 0.3,  # Quick fades (vs 1.0)
        "buffer_time": 0.5,  # Less buffer (vs 1.0)
        "use_interim_results": False,
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": False,
    },
    6: {
        "name": "Congregation Friendly",
        "description": "Comfortable reading speed (220 wpm) with optimized display timing",
        "reading_speed": 220,  # Comfortable reading speed
        "min_display_time": 2.5,  # Optimized
        "fade_duration": 0.3,  # Quick fades
        "buffer_time": 0.5,  # Optimized
        "use_interim_results": False,
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": False,
    },
    7: {
        "name": "Chunk Splitting",
        "description": "Splits long segments (40+ words) for consistent display timing",
        "reading_speed": 220,  # Comfortable reading speed
        "min_display_time": 2.5,  # Optimized
        "fade_duration": 0.3,  # Quick fades
        "buffer_time": 0.5,  # Optimized
        "use_interim_results": False,
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": True,
        "chunk_split_threshold": 40,  # Max words per chunk
        "chunk_min_size": 15,  # Minimum words in a chunk
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
    
    # Chunk splitting fields
    original_segment_id: int = None  # ID of parent segment (if this is a chunk)
    chunk_number: int = 1  # Which chunk this is (1, 2, 3...)
    total_chunks: int = 1  # Total chunks from parent segment
    was_split: bool = False  # True if this came from splitting
    original_word_count: int = None  # Word count before splitting
    
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
    
    def __init__(self, language_names, test_mode_config, font_size=24):
        """
        Initialize display with 1-4 languages
        
        Args:
            language_names: List of language names (1-4 languages)
            test_mode_config: Test mode configuration dict
            font_size: Base font size
        """
        self.font_size = font_size
        self.config = test_mode_config
        self.text_queue = queue.Queue()
        self.is_running = False
        self.is_paused = False
        self.in_catchup_mode = False
        
        # Store language names
        self.language_names = language_names
        self.num_languages = len(language_names)
        
        # Current text being displayed (list for each language)
        self.current_texts = [""] * self.num_languages
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
        
        # Adjust height based on number of languages
        base_height = 300
        per_lang_height = 100
        window_height = base_height + (self.num_languages * per_lang_height)
        window_width = int(screen_width * 0.85)
        
        x_position = (screen_width - window_width) // 2
        y_position = screen_height - window_height - 80
        
        self.root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
        self.root.attributes('-topmost', True)
        
        # Fonts - adjust size based on number of languages
        adjusted_font_size = max(16, self.font_size - (self.num_languages - 1) * 2)
        self.display_font = font.Font(family="Arial", size=adjusted_font_size, weight="bold")
        self.display_font_italic = font.Font(family="Arial", size=adjusted_font_size, weight="bold", slant="italic")
        self.label_font = font.Font(family="Arial", size=12, weight="bold")
        self.status_font = font.Font(family="Arial", size=12, weight="bold")
        self.metrics_font = font.Font(family="Consolas", size=11, weight="bold")
        
        # === TEST INFO BAR (top) ===
        test_info_frame = tk.Frame(self.root, bg='#1a1a2e')
        test_info_frame.pack(fill=tk.X)
        
        self.test_mode_label = tk.Label(
            test_info_frame,
            text=f"TEST MODE {list(TEST_MODES.keys())[list(TEST_MODES.values()).index(test_mode_config)]}: {test_mode_config['name']}",
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
        
        # Queue depth indicator (accurate real-time metric)
        self.queue_label = tk.Label(
            metrics_frame,
            text="Queue: 0",
            font=self.metrics_font,
            fg='#00ff00',
            bg='#0f0f23',
            pady=8,
            padx=15
        )
        self.queue_label.pack(side=tk.LEFT)
        
        # Segments counter
        self.segments_label = tk.Label(
            metrics_frame,
            text="Displayed: 0 | Skipped: 0",
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
            text="ACTIVE - Ctrl+Shift+P to pause",
            font=self.status_font,
            fg='white',
            bg='green',
            pady=8
        )
        self.status_bar.pack(fill=tk.X)
        
        # === MAIN CONTENT ===
        main_frame = tk.Frame(self.root, bg='black')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Colors for different languages
        header_colors = ['yellow', 'cyan', '#ff8888', '#88ff88']
        
        # Create language sections dynamically
        self.lang_frames = []
        self.lang_headers = []
        self.lang_texts = []
        
        for i, lang_name in enumerate(self.language_names):
            # Language frame
            lang_frame = tk.Frame(main_frame, bg='black')
            lang_frame.pack(fill=tk.BOTH, expand=True, pady=5)
            self.lang_frames.append(lang_frame)
            
            # Language header
            header = tk.Label(
                lang_frame,
                text=lang_name.upper(),
                font=self.label_font,
                fg=header_colors[i % len(header_colors)],
                bg='black'
            )
            header.pack()
            self.lang_headers.append(header)
            
            # Language text
            text_label = tk.Label(
                lang_frame,
                text="",
                font=self.display_font,
                fg='white',
                bg='black',
                justify='center',
                wraplength=window_width - 100
            )
            text_label.pack(expand=True)
            self.lang_texts.append(text_label)
            
            # Separator (except after last language)
            if i < len(self.language_names) - 1:
                separator = tk.Frame(main_frame, bg='gray', height=2)
                separator.pack(fill=tk.X, pady=3)
        
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
                # Update queue depth color
                if self.queue_depth <= 1:
                    queue_color = '#00ff00'  # Green - keeping up
                    queue_status = "OK"
                elif self.queue_depth <= 3:
                    queue_color = '#ffff00'  # Yellow - slight backlog
                    queue_status = "Busy"
                else:
                    queue_color = '#ff0000'  # Red - falling behind
                    queue_status = "Behind"
                
                self.root.after(0, lambda c=queue_color, s=queue_status: self.queue_label.config(
                    text=f"Queue: {self.queue_depth} ({s})",
                    fg=c
                ))
                
                # Update segments counter
                self.root.after(0, lambda: self.segments_label.config(
                    text=f"Displayed: {self.segments_displayed} | Skipped: {self.segments_skipped}"
                ))
                
                # Update catchup indicator
                if self.in_catchup_mode:
                    self.root.after(0, lambda: self.catchup_label.config(
                        text="CATCH-UP MODE"
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
    
    def add_translation(self, translations: list, segment_data: SegmentData, is_interim=False):
        """Add translation to queue with tracking data
        
        Args:
            translations: List of translated texts (one per language)
            segment_data: SegmentData object for tracking
            is_interim: Whether this is an interim (non-final) result
        """
        if translations and any(translations):
            self.text_queue.put((translations, segment_data, is_interim))
            self.update_queue_depth(self.text_queue.qsize())
    
    def _process_queue(self):
        """Process translations with timing"""
        while self.is_running:
            try:
                translations, segment_data, is_interim = self.text_queue.get(timeout=0.1)
                self.update_queue_depth(self.text_queue.qsize())
                
                # Ensure translations list matches number of languages
                while len(translations) < self.num_languages:
                    translations.append("")
                
                # Check max latency limit
                if self.config.get('max_latency') and segment_data:
                    current_latency = (datetime.now() - segment_data.timestamp_spoken).total_seconds()
                    if current_latency > self.config['max_latency'] and self.config.get('skip_when_exceeded'):
                        # Skip this segment - too old
                        segment_data.was_skipped = True
                        self.segments_skipped += 1
                        print(f"Skipping segment (latency {current_latency:.1f}s > {self.config['max_latency']}s)")
                        continue
                
                # Update segment queue depth
                if segment_data:
                    segment_data.queue_depth_at_display = self.text_queue.qsize()
                
                # Fade out current if exists
                if self.current_texts[0]:
                    elapsed = (datetime.now() - self.display_start_time).total_seconds()
                    required_time = self._calculate_display_time(self.current_texts[0])
                    
                    if elapsed < required_time:
                        time.sleep(required_time - elapsed)
                    
                    self._fade_out()
                
                # Display new text
                self._fade_in(translations, is_interim)
                
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
            for text_label in self.lang_texts:
                self.root.after(0, lambda l=text_label: l.config(text=""))
            return
        
        fade_steps = 10
        fade_delay = fade_duration / fade_steps
        
        for step in range(fade_steps, -1, -1):
            if not self.is_running:
                break
            alpha = step / fade_steps
            brightness = int(255 * alpha)
            color = f'#{brightness:02x}{brightness:02x}{brightness:02x}'
            
            for text_label in self.lang_texts:
                self.root.after(0, lambda l=text_label, c=color: l.config(fg=c))
            time.sleep(fade_delay)
    
    def _fade_in(self, translations, is_interim=False):
        """Fade in new text"""
        self.current_texts = translations[:self.num_languages]
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
            for i, text_label in enumerate(self.lang_texts):
                text = translations[i] if i < len(translations) else ""
                self.root.after(0, lambda l=text_label, t=text, c=base_color, f=text_font: l.config(text=t, fg=c, font=f))
            return
        
        fade_steps = 10
        fade_delay = fade_duration / fade_steps
        
        for step in range(fade_steps + 1):
            if not self.is_running:
                break
            alpha = step / fade_steps
            brightness = int(255 * alpha)
            color = f'#{brightness:02x}{brightness:02x}{brightness:02x}'
            
            for i, text_label in enumerate(self.lang_texts):
                text = translations[i] if i < len(translations) else ""
                self.root.after(0, lambda l=text_label, t=text, c=color, f=text_font: l.config(text=t, fg=c, font=f))
            time.sleep(fade_delay)
    
    def clear_display(self):
        """Clear display"""
        self.current_texts = [""] * self.num_languages
        for text_label in self.lang_texts:
            text_label.config(text="")
    
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
# AUDIO STREAMERS (Microphone and File)
# =============================================================================

class AudioStreamer:
    """Captures audio from USB interface (microphone)"""
    
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
                print(f"OK - Found USB device: {info['name']}")
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


class AudioFileStreamer:
    """Streams audio from a file (MP3, WAV) at real-time or accelerated speed"""
    
    def __init__(self, file_path: str, playback_speed: float = 1.0, max_duration: float = None):
        """
        Initialize file streamer
        
        Args:
            file_path: Path to audio file (MP3 or WAV)
            playback_speed: 1.0 = real-time, 1.5 = 50% faster, etc.
            max_duration: Maximum duration in seconds (None = use full file)
        """
        self.file_path = file_path
        self.playback_speed = playback_speed
        self.max_duration = max_duration
        self.audio_queue = queue.Queue()
        self.is_recording = False
        self.is_finished = False
        
        # Temp file for converted audio
        self.temp_wav_path = None
        
        # Progress tracking
        self.total_duration = 0
        self.effective_duration = 0  # After applying max_duration limit
        self.current_position = 0
        self.progress_callback = None
        
        # Load and convert audio file
        self._load_audio_file()
    
    def _convert_mp3_to_wav(self, mp3_path: str, max_duration: float = None) -> str:
        """Convert MP3 to WAV using ffmpeg"""
        if not FFMPEG_AVAILABLE:
            raise RuntimeError("ffmpeg required for MP3 files. Install from: https://ffmpeg.org/download.html")
        
        # Create temp file for WAV output
        temp_dir = tempfile.gettempdir()
        temp_wav = os.path.join(temp_dir, f"sermon_test_{int(time.time())}.wav")
        
        # Build ffmpeg command
        cmd = [
            'ffmpeg',
            '-i', mp3_path,
            '-acodec', 'pcm_s16le',  # 16-bit PCM
            '-ar', str(RATE),         # Sample rate (16000)
            '-ac', str(CHANNELS),     # Mono
        ]
        
        # Add duration limit if specified
        if max_duration:
            cmd.extend(['-t', str(max_duration)])
        
        cmd.extend([
            '-y',  # Overwrite output
            temp_wav
        ])
        
        print(f"   Converting MP3 to WAV using ffmpeg...")
        
        try:
            # Run ffmpeg (hide window on Windows)
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                creationflags=creationflags
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg error: {result.stderr}")
            
            return temp_wav
            
        except Exception as e:
            if os.path.exists(temp_wav):
                os.remove(temp_wav)
            raise RuntimeError(f"MP3 conversion failed: {e}")
    
    def _load_audio_file(self):
        """Load audio file and convert to correct format"""
        print(f"\nLoading audio file: {self.file_path}")
        
        file_ext = os.path.splitext(self.file_path)[1].lower()
        
        if file_ext == '.mp3':
            # Convert MP3 to WAV using ffmpeg
            self.temp_wav_path = self._convert_mp3_to_wav(self.file_path, self.max_duration)
            wav_path = self.temp_wav_path
            
        elif file_ext == '.wav':
            wav_path = self.file_path
        else:
            raise ValueError(f"Unsupported audio format: {file_ext}")
        
        # Load WAV file
        with wave.open(wav_path, 'rb') as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            n_frames = wav_file.getnframes()
            
            print(f"   WAV format: {channels}ch, {frame_rate}Hz, {sample_width*8}-bit")
            
            full_duration = n_frames / frame_rate
            
            # For WAV files (not converted MP3), apply max_duration limit
            if file_ext == '.wav' and self.max_duration and self.max_duration < full_duration:
                print(f"   Limiting to first {self.max_duration/60:.1f} minutes of {full_duration/60:.1f} minute file")
                frames_to_read = int(self.max_duration * frame_rate)
                self.total_duration = self.max_duration
            else:
                frames_to_read = n_frames
                self.total_duration = full_duration
            
            # Read frames
            raw_data = wav_file.readframes(frames_to_read)
            
            # Check if conversion is needed (for WAV files that aren't already in correct format)
            if channels != CHANNELS or frame_rate != RATE:
                if file_ext == '.wav' and FFMPEG_AVAILABLE:
                    print("   Converting WAV to required format using ffmpeg...")
                    # Convert WAV using ffmpeg
                    temp_converted = os.path.join(tempfile.gettempdir(), f"sermon_converted_{int(time.time())}.wav")
                    
                    cmd = [
                        'ffmpeg',
                        '-i', wav_path,
                        '-acodec', 'pcm_s16le',
                        '-ar', str(RATE),
                        '-ac', str(CHANNELS),
                    ]
                    
                    if self.max_duration:
                        cmd.extend(['-t', str(self.max_duration)])
                    
                    cmd.extend(['-y', temp_converted])
                    
                    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                    subprocess.run(cmd, capture_output=True, creationflags=creationflags)
                    
                    # Read converted file
                    with wave.open(temp_converted, 'rb') as converted:
                        raw_data = converted.readframes(converted.getnframes())
                        self.total_duration = converted.getnframes() / converted.getframerate()
                    
                    os.remove(temp_converted)
                else:
                    print(f"   WARNING:  WAV format mismatch ({channels}ch, {frame_rate}Hz). May cause issues.")
            
            self.audio_data = raw_data
        
        self.effective_duration = self.total_duration / self.playback_speed
        
        print(f"   OK - Loaded {self.total_duration:.1f} seconds ({self.total_duration/60:.1f} minutes) of audio")
        print(f"   Playback speed: {self.playback_speed}x")
        print(f"   Effective test duration: {self.effective_duration:.1f} seconds ({self.effective_duration/60:.1f} minutes)")
    
    def cleanup(self):
        """Clean up temporary files"""
        if self.temp_wav_path and os.path.exists(self.temp_wav_path):
            try:
                os.remove(self.temp_wav_path)
            except:
                pass
    
    def set_progress_callback(self, callback):
        """Set callback for progress updates: callback(current_seconds, total_seconds)"""
        self.progress_callback = callback
    
    def start_stream(self):
        """Start streaming audio in background thread"""
        self.is_recording = True
        self.is_finished = False
        self.stream_thread = threading.Thread(target=self._stream_audio, daemon=True)
        self.stream_thread.start()
        print("\n🎵 Audio file streaming started...")
    
    def _stream_audio(self):
        """Stream audio data at real-time (or accelerated) pace"""
        # Calculate chunk timing
        bytes_per_second = RATE * CHANNELS * 2  # 16-bit = 2 bytes
        chunk_bytes = CHUNK * CHANNELS * 2
        chunk_duration = CHUNK / RATE  # Duration of one chunk in seconds
        
        # Adjusted sleep time based on playback speed
        sleep_time = chunk_duration / self.playback_speed
        
        # Stream start time (for simulating real-time timestamps)
        stream_start = datetime.now()
        audio_position = 0  # Position in the audio timeline
        
        offset = 0
        total_bytes = len(self.audio_data)
        
        while offset < total_bytes and self.is_recording:
            # Get chunk of audio data
            chunk = self.audio_data[offset:offset + chunk_bytes]
            
            # Calculate simulated timestamp (when this audio "would have been spoken")
            audio_position = offset / bytes_per_second
            simulated_timestamp = stream_start + timedelta(seconds=audio_position)
            
            # Queue the chunk with its timestamp
            self.audio_queue.put((chunk, simulated_timestamp))
            
            # Update progress
            self.current_position = audio_position
            if self.progress_callback:
                self.progress_callback(audio_position, self.total_duration)
            
            offset += chunk_bytes
            
            # Sleep to simulate real-time (adjusted for playback speed)
            time.sleep(sleep_time)
        
        # Mark as finished
        self.is_finished = True
        self.is_recording = False
        print("\nOK - Audio file playback complete")
    
    def stop_stream(self):
        """Stop streaming"""
        self.is_recording = False
    
    def audio_generator(self) -> Generator[tuple, None, None]:
        """Generate audio chunks with timestamps"""
        while self.is_recording or not self.audio_queue.empty():
            try:
                data, timestamp = self.audio_queue.get(timeout=1)
                yield data, timestamp
            except queue.Empty:
                if self.is_finished:
                    break
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
    
    def __init__(self, source_language, target_languages, display_languages, test_mode: int,
                 audio_source: str = "microphone", audio_file_path: str = None, 
                 playback_speed: float = 1.0, max_duration: float = None):
        """
        Initialize test harness
        
        Args:
            source_language: (code, name) tuple
            target_languages: List of (code, name) tuples
            display_languages: List of 2 (code, name) tuples for display
            test_mode: 0-4 test mode number
            audio_source: "microphone" or "file"
            audio_file_path: Path to audio file (if audio_source is "file")
            playback_speed: Playback speed multiplier (1.0 = real-time)
            max_duration: Maximum audio duration in seconds (None = full file)
        """
        # Credentials
        creds_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 
                                    'credentials/sermon-streaming.json')
        credentials = service_account.Credentials.from_service_account_file(creds_path)
        
        self.speech_client = speech.SpeechClient(credentials=credentials)
        self.translate_client = translate.Client(credentials=credentials)
        
        self.source_language = source_language
        self.target_languages = target_languages
        self.display_languages = display_languages
        
        # Audio source configuration
        self.audio_source = audio_source
        self.audio_file_path = audio_file_path
        self.playback_speed = playback_speed
        self.max_duration = max_duration
        
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
        language_names = [lang[1] for lang in display_languages]
        self.display = TestHarnessDisplay(
            language_names,
            self.test_config,
            font_size=28
        )
        
        # Add audio progress indicator for file mode
        if audio_source == "file":
            self._add_progress_bar()
        
        # Keyboard bindings
        self.display.root.bind('<Control-Shift-P>', self._pause)
        self.display.root.bind('<Control-Shift-p>', self._pause)
        self.display.root.bind('<Control-Shift-R>', self._resume)
        self.display.root.bind('<Control-Shift-r>', self._resume)
        self.display.root.bind('<Control-Shift-S>', self._stop)
        self.display.root.bind('<Control-Shift-s>', self._stop)
        
        # Initialize appropriate audio streamer
        if audio_source == "file":
            self.audio_streamer = AudioFileStreamer(audio_file_path, playback_speed, max_duration)
            self.audio_streamer.set_progress_callback(self._update_progress)
        else:
            self.audio_streamer = AudioStreamer()
        
        # Track last audio timestamp for latency calculation
        self.last_audio_timestamp = None
        
        # Queue drain time tracking (most reliable latency measure)
        self.audio_end_time = None
        self.final_display_time = None
        
        print(f"\nTEST - TEST HARNESS INITIALIZED")
        print(f"   Mode: {test_mode} - {self.test_config['name']}")
        print(f"   Description: {self.test_config['description']}")
        print(f"   Audio Source: {audio_source.upper()}")
        if audio_source == "file":
            print(f"   File: {os.path.basename(audio_file_path)}")
            if max_duration:
                print(f"   Duration Limit: {max_duration/60:.1f} minutes")
            print(f"   Playback Speed: {playback_speed}x")
        print(f"   Input: {source_language[1]}")
        print(f"   Outputs: {', '.join([l[1] for l in target_languages])}")
    
    def _add_progress_bar(self):
        """Add audio progress bar for file playback mode"""
        progress_frame = tk.Frame(self.display.root, bg='#1a1a2e')
        progress_frame.pack(fill=tk.X, after=self.display.test_mode_label.master)
        
        self.progress_label = tk.Label(
            progress_frame,
            text="Audio: 0:00 / 0:00 (0%)",
            font=('Consolas', 10),
            fg='#888888',
            bg='#1a1a2e',
            pady=3
        )
        self.progress_label.pack(side=tk.LEFT, padx=10)
        
        # Progress bar canvas
        self.progress_canvas = tk.Canvas(
            progress_frame,
            width=300,
            height=12,
            bg='#333333',
            highlightthickness=0
        )
        self.progress_canvas.pack(side=tk.LEFT, padx=10, pady=3)
        self.progress_bar = self.progress_canvas.create_rectangle(0, 0, 0, 12, fill='#00aa00')
    
    def _update_progress(self, current_seconds, total_seconds):
        """Update audio progress display"""
        if hasattr(self, 'progress_label'):
            current_str = f"{int(current_seconds//60)}:{int(current_seconds%60):02d}"
            total_str = f"{int(total_seconds//60)}:{int(total_seconds%60):02d}"
            percent = (current_seconds / total_seconds * 100) if total_seconds > 0 else 0
            
            self.display.root.after(0, lambda: self.progress_label.config(
                text=f"Audio: {current_str} / {total_str} ({percent:.0f}%)"
            ))
            
            # Update progress bar
            bar_width = int((current_seconds / total_seconds) * 300) if total_seconds > 0 else 0
            self.display.root.after(0, lambda w=bar_width: self.progress_canvas.coords(
                self.progress_bar, 0, 0, w, 12
            ))
    
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
    
    def split_text_into_chunks(self, text: str, max_words: int = 40, min_words: int = 15) -> List[str]:
        """
        Split text into chunks at sentence boundaries.
        
        Priority: 
        1. Split at periods (.)
        2. Split at commas (,) or semicolons (;)
        3. Split at word boundary
        
        Args:
            text: Text to split
            max_words: Maximum words per chunk
            min_words: Minimum words per chunk (avoid tiny fragments)
            
        Returns:
            List of text chunks
        """
        words = text.split()
        total_words = len(words)
        
        # If already under threshold, return as-is
        if total_words <= max_words:
            return [text]
        
        chunks = []
        current_position = 0
        
        while current_position < total_words:
            remaining_words = total_words - current_position
            
            # If remaining is small enough, take it all
            if remaining_words <= max_words:
                chunk = ' '.join(words[current_position:])
                chunks.append(chunk)
                break
            
            # Look for a good split point within the max_words window
            window_end = min(current_position + max_words, total_words)
            window_text = ' '.join(words[current_position:window_end])
            
            # Try to find split points (sentence endings preferred)
            split_point = None
            
            # Priority 1: Look for period followed by space (sentence end)
            for i in range(window_end - 1, current_position + min_words - 1, -1):
                word = words[i]
                if word.endswith('.') or word.endswith('?') or word.endswith('!'):
                    split_point = i + 1
                    break
            
            # Priority 2: Look for comma or semicolon
            if split_point is None:
                for i in range(window_end - 1, current_position + min_words - 1, -1):
                    word = words[i]
                    if word.endswith(',') or word.endswith(';') or word.endswith(':'):
                        split_point = i + 1
                        break
            
            # Priority 3: Just split at max_words
            if split_point is None:
                split_point = window_end
            
            # Create chunk
            chunk = ' '.join(words[current_position:split_point])
            chunks.append(chunk)
            current_position = split_point
        
        return chunks
    
    def split_translations_into_chunks(self, original_text: str, translations: Dict[str, str], 
                                       max_words: int = 40, min_words: int = 15) -> List[Dict[str, str]]:
        """
        Split translations into synchronized chunks.
        Each translation is split proportionally to maintain alignment.
        
        Returns:
            List of translation dicts, one per chunk
        """
        # Split original text to determine chunk count
        original_chunks = self.split_text_into_chunks(original_text, max_words, min_words)
        num_chunks = len(original_chunks)
        
        if num_chunks == 1:
            return [translations]
        
        # Split each translation into the same number of chunks
        chunked_translations = []
        
        for i in range(num_chunks):
            chunk_dict = {}
            for lang_name, trans_text in translations.items():
                trans_chunks = self.split_text_into_chunks(trans_text, max_words, min_words)
                # Get corresponding chunk (or last chunk if fewer)
                if i < len(trans_chunks):
                    chunk_dict[lang_name] = trans_chunks[i]
                else:
                    chunk_dict[lang_name] = ""
            chunked_translations.append(chunk_dict)
        
        return chunked_translations
    
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
                'original_segment_id': segment.original_segment_id or '',
                'chunk_number': segment.chunk_number,
                'total_chunks': segment.total_chunks,
                'was_split': segment.was_split,
                'original_word_count': segment.original_word_count or '',
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
            'is_interim', 'was_skipped', 
            'original_segment_id', 'chunk_number', 'total_chunks', 
            'was_split', 'original_word_count',
            'text_original'
        ])
        self.csv_writer.writeheader()
        
        # Text log file
        log_filename = f"test_results/{mode_name}_{timestamp}_log.txt"
        self.output_file = open(log_filename, 'w', encoding='utf-8')
        self.output_file.write(f"TEST HARNESS LOG\n")
        self.output_file.write(f"{'='*70}\n")
        self.output_file.write(f"Mode: {self.test_mode} - {self.test_config['name']}\n")
        self.output_file.write(f"Description: {self.test_config['description']}\n")
        self.output_file.write(f"Audio Source: {self.audio_source}\n")
        if self.audio_source == "file":
            self.output_file.write(f"Audio File: {self.audio_file_path}\n")
            if self.max_duration:
                self.output_file.write(f"Duration Limit: {self.max_duration/60:.1f} minutes\n")
            self.output_file.write(f"Playback Speed: {self.playback_speed}x\n")
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
        
        if self.audio_source == "file":
            if self.max_duration:
                print(f"   Will process first {self.max_duration/60:.0f} minutes of audio")
            print(f"   Audio file will play automatically when you press Ctrl+Shift+R")
            print(f"   Test will auto-complete when audio finishes")
        
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
            # Check if file playback finished
            if self.audio_source == "file" and hasattr(self.audio_streamer, 'is_finished'):
                if self.audio_streamer.is_finished and self.audio_streamer.audio_queue.empty():
                    # Record when audio ended
                    if self.audio_end_time is None:
                        self.audio_end_time = datetime.now()
                        print(f"\nFINISHED - Audio file playback complete at {self.audio_end_time.strftime('%H:%M:%S')}")
                        print(f"   Waiting for display queue to drain...")
                    
                    # Wait for display queue to empty
                    if self.display.text_queue.empty():
                        # Record final display time
                        self.final_display_time = datetime.now()
                        queue_drain_time = (self.final_display_time - self.audio_end_time).total_seconds()
                        print(f"\nOK - Queue drained at {self.final_display_time.strftime('%H:%M:%S')}")
                        print(f"   QUEUE DRAIN TIME: {queue_drain_time:.1f} seconds")
                        print(f"   (This is your actual real-world latency)")
                        
                        time.sleep(2)  # Brief pause to show final translation
                        self.display.root.after(0, self._stop)
                        break
                    else:
                        time.sleep(0.5)
                        continue
            
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
                        # For file source, check if finished
                        if self.audio_source == "file" and hasattr(self.audio_streamer, 'is_finished'):
                            if self.audio_streamer.is_finished and self.audio_streamer.audio_queue.empty():
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
                            print(f"(interim) {transcript}", end='\r')
                            continue
                        
                        # Create base segment data
                        self.segment_counter += 1
                        original_segment_id = self.segment_counter
                        timestamp_spoken = self.last_audio_timestamp or batch_start_time
                        timestamp_recognized = datetime.now()
                        original_word_count = len(transcript.split())
                        
                        # Translate
                        translations = self.translate_to_multiple(transcript)
                        timestamp_translated = datetime.now()
                        
                        # Check if chunk splitting is enabled and needed
                        chunk_split_enabled = self.test_config.get('chunk_split_enabled', False)
                        chunk_threshold = self.test_config.get('chunk_split_threshold', 40)
                        chunk_min = self.test_config.get('chunk_min_size', 15)
                        
                        if chunk_split_enabled and original_word_count > chunk_threshold:
                            # Split the text into chunks
                            original_chunks = self.split_text_into_chunks(transcript, chunk_threshold, chunk_min)
                            translation_chunks = self.split_translations_into_chunks(
                                transcript, translations, chunk_threshold, chunk_min
                            )
                            total_chunks = len(original_chunks)
                            
                            # Log to console
                            print(f"[Final] [{datetime.now().strftime('%H:%M:%S')}] Original: {original_word_count} words")
                            print(f"   SPLIT -> {total_chunks} chunks ({', '.join([str(len(c.split())) for c in original_chunks])} words)")
                            
                            # Process each chunk
                            for chunk_num, (orig_chunk, trans_chunk) in enumerate(zip(original_chunks, translation_chunks), 1):
                                chunk_word_count = len(orig_chunk.split())
                                
                                # Create segment for this chunk
                                if chunk_num > 1:
                                    self.segment_counter += 1
                                
                                chunk_segment = SegmentData(
                                    segment_id=self.segment_counter,
                                    text_original=orig_chunk,
                                    text_translated=trans_chunk,
                                    word_count=chunk_word_count,
                                    timestamp_spoken=timestamp_spoken,
                                    timestamp_recognized=timestamp_recognized,
                                    timestamp_translated=timestamp_translated,
                                    timestamp_queued=datetime.now(),
                                    is_interim=not is_final,
                                    queue_depth_at_queue=self.display.text_queue.qsize(),
                                    original_segment_id=original_segment_id,
                                    chunk_number=chunk_num,
                                    total_chunks=total_chunks,
                                    was_split=True,
                                    original_word_count=original_word_count
                                )
                                
                                # Display chunk translations
                                for lang_name, translation in trans_chunk.items():
                                    print(f"   -> {lang_name} [{chunk_num}/{total_chunks}]: {translation[:80]}...")
                                
                                # Build display list
                                display_translations = [
                                    trans_chunk.get(lang[1], "") 
                                    for lang in self.display_languages
                                ]
                                self.display.add_translation(display_translations, chunk_segment, not is_final)
                                
                                # Write to CSV
                                self._write_csv_row(chunk_segment)
                                
                                # Add to session
                                self.session.add_segment(chunk_segment)
                            
                            # Log to file
                            if self.output_file:
                                self.output_file.write(f"[{datetime.now().strftime('%H:%M:%S')}] Segment {original_segment_id} SPLIT into {total_chunks} chunks\n")
                                self.output_file.write(f"  Original: {original_word_count} words\n")
                                self.output_file.write(f"  Chunks: {', '.join([str(len(c.split())) for c in original_chunks])} words\n")
                                self.output_file.write(f"  Text: {transcript[:100]}...\n\n")
                                self.output_file.flush()
                        
                        else:
                            # No splitting - process as single segment
                            segment = SegmentData(
                                segment_id=self.segment_counter,
                                text_original=transcript,
                                text_translated=translations,
                                word_count=original_word_count,
                                timestamp_spoken=timestamp_spoken,
                                timestamp_recognized=timestamp_recognized,
                                timestamp_translated=timestamp_translated,
                                timestamp_queued=datetime.now(),
                                is_interim=not is_final,
                                queue_depth_at_queue=self.display.text_queue.qsize()
                            )
                            
                            # Log to console
                            status = "[Final]" if is_final else "[Interim]"
                            print(f"{status} [{datetime.now().strftime('%H:%M:%S')}] {transcript}")
                            
                            for lang_name, translation in translations.items():
                                print(f"   -> {lang_name}: {translation}")
                            
                            # Build list of translations in display order
                            display_translations = [
                                translations.get(lang[1], "") 
                                for lang in self.display_languages
                            ]
                            self.display.add_translation(display_translations, segment, not is_final)
                            
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
                    # For file source, this might mean we're done
                    if self.audio_source == "file" and hasattr(self.audio_streamer, 'is_finished'):
                        if self.audio_streamer.is_finished:
                            continue
                    if not self.is_paused:
                        print(f"\nWARNING:  Stream timeout - restarting...")
                    time.sleep(1)
                    continue
                else:
                    print(f"\nERROR: Error: {e}")
                    break
    
    def stop(self):
        """Stop and generate summary"""
        print("\nSTOP -  Stopping test...")
        
        self.session.end_time = datetime.now()
        
        if self.active_start_time and not self.is_paused:
            self.total_active_time += (datetime.now() - self.active_start_time).total_seconds()
        
        self.audio_streamer.stop_stream()
        
        # Cleanup temp files for file streamer
        if hasattr(self.audio_streamer, 'cleanup'):
            self.audio_streamer.cleanup()
        
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
        
        # Calculate queue wait times (translation received to displayed)
        queue_wait_times = [s.latency_queue_wait for s in self.session.segments 
                          if s.latency_queue_wait is not None and not s.was_skipped]
        
        if queue_wait_times:
            avg_queue_wait = sum(queue_wait_times) / len(queue_wait_times)
            max_queue_wait = max(queue_wait_times)
            min_queue_wait = min(queue_wait_times)
        else:
            avg_queue_wait = 0
            max_queue_wait = 0
            min_queue_wait = 0
        
        # Calculate queue wait trend (first half vs second half)
        if len(queue_wait_times) > 4:
            first_half = queue_wait_times[:len(queue_wait_times)//2]
            second_half = queue_wait_times[len(queue_wait_times)//2:]
            first_avg = sum(first_half) / len(first_half)
            second_avg = sum(second_half) / len(second_half)
            
            if self.session.duration_seconds > 0:
                segments_per_minute = len(self.session.segments) / (self.session.duration_seconds / 60)
                trend_per_segment = (second_avg - first_avg) / (len(queue_wait_times) // 2)
                trend_per_minute = trend_per_segment * segments_per_minute
            else:
                trend_per_minute = 0
        else:
            trend_per_minute = 0
            first_avg = 0
            second_avg = 0
        
        # Calculate queue drain time (most reliable overall latency measure)
        if self.audio_end_time and self.final_display_time:
            queue_drain_time = (self.final_display_time - self.audio_end_time).total_seconds()
            queue_drain_str = f"{queue_drain_time:.1f} seconds"
        else:
            queue_drain_time = None
            queue_drain_str = "Not measured (live audio or early stop)"
        
        # Pre-calculate values for f-string
        duration_limit_str = f"{self.max_duration/60:.0f} minutes" if self.max_duration else "Full file"
        segments_per_min = len(self.session.segments)/(self.session.duration_seconds/60) if self.session.duration_seconds > 0 else 0
        trend_direction = '(INCREASING - queue building up)' if trend_per_minute > 0.2 else '(STABLE)' if abs(trend_per_minute) < 0.2 else '(DECREASING)'
        trend_sign = '+' if trend_per_minute > 0 else ''
        
        # Queue wait distribution
        total_waits = len(queue_wait_times) if queue_wait_times else 1
        under_3 = len([w for w in queue_wait_times if w < 3])
        wait_3_5 = len([w for w in queue_wait_times if 3 <= w < 5])
        wait_5_8 = len([w for w in queue_wait_times if 5 <= w < 8])
        wait_8_12 = len([w for w in queue_wait_times if 8 <= w < 12])
        over_12 = len([w for w in queue_wait_times if w >= 12])
        
        # Chunk splitting analysis
        chunk_split_enabled = self.test_config.get('chunk_split_enabled', False)
        chunk_threshold = self.test_config.get('chunk_split_threshold', 40)
        
        # Get word counts
        word_counts = [s.word_count for s in self.session.segments]
        original_word_counts = [s.original_word_count for s in self.session.segments if s.original_word_count]
        
        # Count split segments
        split_segments = [s for s in self.session.segments if s.was_split]
        non_split_segments = [s for s in self.session.segments if not s.was_split]
        
        # Unique original segments that were split
        original_segments_split = len(set(s.original_segment_id for s in split_segments if s.original_segment_id))
        
        # Chunks created from splits
        chunks_from_splits = len(split_segments)
        
        # Word count distribution (after splitting)
        wc_under_20 = len([w for w in word_counts if w < 20])
        wc_20_40 = len([w for w in word_counts if 20 <= w < 40])
        wc_41_60 = len([w for w in word_counts if 41 <= w <= 60])
        wc_61_100 = len([w for w in word_counts if 61 <= w <= 100])
        wc_over_100 = len([w for w in word_counts if w > 100])
        total_wc = len(word_counts) if word_counts else 1
        
        # Build chunk splitting section if enabled
        if chunk_split_enabled:
            chunk_section = f"""
{'='*70}
CHUNK SPLITTING ANALYSIS
{'='*70}
Splitting Threshold: {chunk_threshold} words
Minimum Chunk Size: {self.test_config.get('chunk_min_size', 15)} words

SPLITTING STATISTICS
--------------------
Original segments from Google:    {original_segments_split + len(non_split_segments)}
Segments that needed splitting:   {original_segments_split}
Total chunks after splitting:     {len(self.session.segments)}
New chunks created from splits:   {chunks_from_splits}

WORD COUNT DISTRIBUTION (After Splitting)
-----------------------------------------
Under 20 words:  {wc_under_20:3d} ({100*wc_under_20/total_wc:.1f}%)
20-40 words:     {wc_20_40:3d} ({100*wc_20_40/total_wc:.1f}%)
41-60 words:     {wc_41_60:3d} ({100*wc_41_60/total_wc:.1f}%) {'<-- Over threshold' if wc_41_60 > 0 else ''}
61-100 words:    {wc_61_100:3d} ({100*wc_61_100/total_wc:.1f}%) {'<-- Over threshold' if wc_61_100 > 0 else ''}
Over 100 words:  {wc_over_100:3d} ({100*wc_over_100/total_wc:.1f}%) {'<-- Over threshold' if wc_over_100 > 0 else ''}

"""
        else:
            # Show word count distribution for non-split modes
            avg_wc = sum(word_counts) / len(word_counts) if word_counts else 0
            max_wc = max(word_counts) if word_counts else 0
            over_40 = len([w for w in word_counts if w > 40])
            over_100 = len([w for w in word_counts if w > 100])
            
            chunk_section = f"""
{'='*70}
WORD COUNT ANALYSIS
{'='*70}
Average Words/Segment: {avg_wc:.1f}
Maximum Words/Segment: {max_wc}
Segments over 40 words:  {over_40} ({100*over_40/total_wc:.1f}%)
Segments over 100 words: {over_100} ({100*over_100/total_wc:.1f}%)

WORD COUNT DISTRIBUTION
-----------------------
Under 20 words:  {wc_under_20:3d} ({100*wc_under_20/total_wc:.1f}%)
20-40 words:     {wc_20_40:3d} ({100*wc_20_40/total_wc:.1f}%)
41-60 words:     {wc_41_60:3d} ({100*wc_41_60/total_wc:.1f}%)
61-100 words:    {wc_61_100:3d} ({100*wc_61_100/total_wc:.1f}%)
Over 100 words:  {wc_over_100:3d} ({100*wc_over_100/total_wc:.1f}%)

"""
        
        summary = f"""
{'='*70}
TEST SUMMARY: {self.test_config['name']}
{'='*70}

TEST CONFIGURATION
------------------
Mode: {self.test_mode} - {self.test_config['name']}
Description: {self.test_config['description']}
Audio Source: {self.audio_source}
Duration Limit: {duration_limit_str}
Reading Speed: {self.test_config['reading_speed']} wpm
Min Display Time: {self.test_config['min_display_time']}s
Fade Duration: {self.test_config['fade_duration']}s
Chunk Splitting: {'Enabled (threshold: ' + str(chunk_threshold) + ' words)' if chunk_split_enabled else 'Disabled'}

TIMING STATISTICS
-----------------
Test Duration: {self.session.duration_seconds/60:.1f} minutes
Active Time: {self.total_active_time/60:.1f} minutes

SEGMENT STATISTICS
------------------
Segments Processed: {len(self.session.segments)}
Segments Displayed: {self.display.segments_displayed}
Segments Skipped:   {self.display.segments_skipped}
Segments/Minute:    {segments_per_min:.1f}

{'='*70}
QUEUE DRAIN TIME (Overall System Latency)
{'='*70}
Time from audio end to last translation displayed: {queue_drain_str}

This represents the TOTAL end-to-end delay your congregation experiences
from when words are spoken to when translation appears on screen.
{'='*70}

QUEUE WAIT TIME (Translation Ready -> Displayed)
{'='*70}
This measures how long each translation waits in the display queue
after being translated, before it appears on screen.

Average Wait:  {avg_queue_wait:.2f} seconds
Maximum Wait:  {max_queue_wait:.2f} seconds
Minimum Wait:  {min_queue_wait:.2f} seconds

QUEUE WAIT TREND
----------------
First Half Average:  {first_avg:.2f} seconds
Second Half Average: {second_avg:.2f} seconds
Trend: {trend_sign}{trend_per_minute:.2f} sec/minute {trend_direction}

QUEUE WAIT DISTRIBUTION
-----------------------
Under 3 seconds:  {under_3:3d} ({100*under_3/total_waits:.1f}%) - Excellent
3-5 seconds:      {wait_3_5:3d} ({100*wait_3_5/total_waits:.1f}%) - Good
5-8 seconds:      {wait_5_8:3d} ({100*wait_5_8/total_waits:.1f}%) - Acceptable
8-12 seconds:     {wait_8_12:3d} ({100*wait_8_12/total_waits:.1f}%) - Slow
Over 12 seconds:  {over_12:3d} ({100*over_12/total_waits:.1f}%) - Too slow
{chunk_section}
{'='*70}
ANALYSIS
{'='*70}
Queue Drain Time ({queue_drain_str}) includes:
  - Google Speech Recognition delay (~3-5 sec)
  - Translation API delay (~1 sec)  
  - Display queue wait ({avg_queue_wait:.1f} sec average)
  - Final segment display time

Average Queue Wait ({avg_queue_wait:.2f}s) vs Drain Time ({queue_drain_str}):
  If these are close, translations are keeping up with speech.
  If drain time >> queue wait, there may be recognition delays.

{'='*70}
"""
        
        # Write to file
        with open(summary_filename, 'w', encoding='utf-8') as f:
            f.write(summary)
        
        # Print to console
        print(summary)
        print(f"\nSummary saved to: {summary_filename}")


# =============================================================================
# CONFIGURATION MENUS
# =============================================================================

# Default audio folder
DEFAULT_AUDIO_FOLDER = r"C:\Users\sermon_translator\AppData\Local\software\projects\sermon_translation\audio"

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
            print(f"     Shows interim results (text may change)")
        if config.get('max_latency'):
            print(f"     Max latency: {config['max_latency']}s")
        if config.get('catchup_enabled'):
            print(f"     Catchup mode enabled (threshold: {config.get('catchup_threshold')} items)")
        if config.get('chunk_split_enabled'):
            print(f"     Chunk splitting: max {config.get('chunk_split_threshold')} words per chunk")
    
    print("\n" + "-"*70)
    print("  L. View last test results")
    print("  C. Compare all test results")
    print("  Q. Quit")
    print("-"*70)
    
    while True:
        choice = input("\nEnter choice (0-7, L, C, Q): ").strip().upper()
        
        if choice == 'Q':
            print("Exiting...")
            exit(0)
        elif choice == 'L':
            view_last_results()
            return select_test_mode()  # Return to menu
        elif choice == 'C':
            compare_all_results()
            return select_test_mode()  # Return to menu
        elif choice in ['0', '1', '2', '3', '4', '5', '6', '7']:
            return int(choice)
        else:
            print("Invalid choice. Try again.")


def select_audio_source():
    """Select audio input source"""
    print("\n" + "="*70)
    print("    AUDIO SOURCE SELECTION")
    print("="*70)
    
    print("\n  1. Live Microphone (USB/Focusrite)")
    print("  2. Audio File (MP3/WAV) - Recommended for testing")
    
    while True:
        choice = input("\nSelect audio source (1-2): ").strip()
        
        if choice == "1":
            return "microphone", None, 1.0, None
        
        elif choice == "2":
            # File selection
            print("\n" + "-"*70)
            print("AUDIO FILE SELECTION")
            print("-"*70)
            
            # Check default folder
            if os.path.exists(DEFAULT_AUDIO_FOLDER):
                print(f"\nDefault audio folder: {DEFAULT_AUDIO_FOLDER}")
                files = [f for f in os.listdir(DEFAULT_AUDIO_FOLDER) 
                        if f.lower().endswith(('.mp3', '.wav'))]
                
                if files:
                    print("\nAvailable audio files:")
                    for i, f in enumerate(files, 1):
                        # Get file size
                        size = os.path.getsize(os.path.join(DEFAULT_AUDIO_FOLDER, f))
                        size_mb = size / (1024 * 1024)
                        print(f"  {i}. {f} ({size_mb:.1f} MB)")
                    
                    print(f"\n  B. Browse for different file")
                    print(f"  P. Enter path manually")
                    
                    while True:
                        file_choice = input("\nSelect file (number, B, or P): ").strip().upper()
                        
                        if file_choice == 'B':
                            file_path = browse_for_file()
                            if file_path:
                                break
                        elif file_choice == 'P':
                            file_path = input("Enter full path to audio file: ").strip()
                            if os.path.exists(file_path):
                                break
                            print("ERROR: File not found.")
                        else:
                            try:
                                idx = int(file_choice) - 1
                                if 0 <= idx < len(files):
                                    file_path = os.path.join(DEFAULT_AUDIO_FOLDER, files[idx])
                                    break
                                print("ERROR: Invalid number.")
                            except ValueError:
                                print("ERROR: Invalid choice.")
                else:
                    print("No audio files found in default folder.")
                    file_path = input("Enter full path to audio file: ").strip()
            else:
                print(f"Default folder not found: {DEFAULT_AUDIO_FOLDER}")
                file_path = input("Enter full path to audio file: ").strip()
            
            if not os.path.exists(file_path):
                print("ERROR: File not found. Using microphone instead.")
                return "microphone", None, 1.0, None
            
            # Duration limit selection
            print("\n" + "-"*70)
            print("DURATION LIMIT")
            print("-"*70)
            print("\nHow much of the audio file should be used?")
            print("\n  1. Use full file (no limit)")
            print("  2. First 15 minutes only (recommended for initial testing)")
            print("  3. First 30 minutes")
            print("  4. First 45 minutes")
            print("  5. Custom duration")
            
            while True:
                duration_choice = input("\nSelect duration (1-5) [default: 2]: ").strip()
                
                if duration_choice == "" or duration_choice == "2":
                    max_duration = 15 * 60  # 15 minutes in seconds
                    print(f"OK - Will use first 15 minutes of audio")
                    break
                elif duration_choice == "1":
                    max_duration = None  # No limit
                    print(f"OK - Will use full audio file")
                    break
                elif duration_choice == "3":
                    max_duration = 30 * 60
                    print(f"OK - Will use first 30 minutes of audio")
                    break
                elif duration_choice == "4":
                    max_duration = 45 * 60
                    print(f"OK - Will use first 45 minutes of audio")
                    break
                elif duration_choice == "5":
                    custom = input("Enter duration in minutes: ").strip()
                    try:
                        max_duration = float(custom) * 60
                        print(f"OK - Will use first {float(custom):.1f} minutes of audio")
                        break
                    except ValueError:
                        print("ERROR: Invalid number.")
                else:
                    print("ERROR: Invalid choice.")
            
            # Playback speed selection
            print("\n" + "-"*70)
            print("PLAYBACK SPEED")
            print("-"*70)
            print("\n  1. 1.0x - Real-time (recommended for accurate testing)")
            print("  2. 1.5x - 50% faster (shorter test, may affect recognition)")
            print("  3. 2.0x - Double speed (quick test, lower accuracy)")
            
            while True:
                speed_choice = input("\nSelect playback speed (1-3) [default: 1]: ").strip()
                if speed_choice == "" or speed_choice == "1":
                    playback_speed = 1.0
                    break
                elif speed_choice == "2":
                    playback_speed = 1.5
                    break
                elif speed_choice == "3":
                    playback_speed = 2.0
                    break
                print("ERROR: Invalid choice.")
            
            # Calculate effective test time
            if max_duration:
                effective_minutes = (max_duration / playback_speed) / 60
            else:
                effective_minutes = "full file"
            
            print(f"\nOK - Audio source: FILE")
            print(f"  File: {os.path.basename(file_path)}")
            print(f"  Duration limit: {max_duration/60:.0f} minutes" if max_duration else "  Duration limit: None (full file)")
            print(f"  Speed: {playback_speed}x")
            if max_duration:
                print(f"  Effective test time: ~{effective_minutes:.1f} minutes")
            
            return "file", file_path, playback_speed, max_duration
        
        print("ERROR: Invalid choice. Enter 1 or 2.")


def browse_for_file():
    """Open file browser dialog"""
    try:
        root = tk.Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            title="Select Audio File",
            initialdir=DEFAULT_AUDIO_FOLDER if os.path.exists(DEFAULT_AUDIO_FOLDER) else os.path.expanduser("~"),
            filetypes=[
                ("Audio files", "*.mp3 *.wav"),
                ("MP3 files", "*.mp3"),
                ("WAV files", "*.wav"),
                ("All files", "*.*")
            ]
        )
        root.destroy()
        return file_path if file_path else None
    except Exception as e:
        print(f"WARNING:  File browser error: {e}")
        return None


def view_last_results():
    """View the most recent test results"""
    results_dir = "test_results"
    if not os.path.exists(results_dir):
        print("\nNo test results found.")
        input("Press Enter to continue...")
        return
    
    # Find most recent summary file
    summary_files = [f for f in os.listdir(results_dir) if f.endswith('_summary.txt')]
    if not summary_files:
        print("\nNo summary files found.")
        input("Press Enter to continue...")
        return
    
    summary_files.sort(reverse=True)
    latest = os.path.join(results_dir, summary_files[0])
    
    print(f"\nLatest results: {summary_files[0]}\n")
    with open(latest, 'r', encoding='utf-8') as f:
        print(f.read())
    
    input("\nPress Enter to continue...")


def compare_all_results():
    """Compare results from all test modes"""
    results_dir = "test_results"
    if not os.path.exists(results_dir):
        print("\nNo test results found.")
        input("Press Enter to continue...")
        return
    
    # Find all summary files
    summary_files = [f for f in os.listdir(results_dir) if f.endswith('_summary.txt')]
    if not summary_files:
        print("\nNo summary files found.")
        input("Press Enter to continue...")
        return
    
    print("\n" + "="*70)
    print("    TEST RESULTS COMPARISON")
    print("="*70)
    
    # Parse summaries and display comparison table
    results = []
    for sf in summary_files:
        filepath = os.path.join(results_dir, sf)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # Extract mode name from filename
            mode_name = sf.split('_')[0].replace('_', ' ').title()
            
            # Try to extract values
            try:
                # Queue drain time
                if 'audio end to last translation displayed:' in content:
                    drain_section = content.split('audio end to last translation displayed:')[1]
                    drain_str = drain_section.split('seconds')[0].strip()
                    try:
                        queue_drain = float(drain_str)
                    except:
                        queue_drain = None
                else:
                    queue_drain = None
                
                # Queue wait time (new format)
                if 'Average Wait:' in content:
                    avg_wait_str = content.split('Average Wait:')[1].split('seconds')[0].strip()
                    try:
                        avg_queue_wait = float(avg_wait_str)
                    except:
                        avg_queue_wait = None
                else:
                    avg_queue_wait = None
                
                # Segments Processed
                if 'Segments Processed:' in content:
                    segments = int(content.split('Segments Processed:')[1].split('\n')[0].strip())
                elif 'Total Segments:' in content:
                    segments = int(content.split('Total Segments:')[1].split('\n')[0].strip())
                else:
                    segments = 0
                
                # Segments Skipped
                if 'Segments Skipped:' in content:
                    skipped = int(content.split('Segments Skipped:')[1].split('\n')[0].strip())
                else:
                    skipped = 0
                
                # Duration
                if 'Test Duration:' in content:
                    duration_str = content.split('Test Duration:')[1].split('minutes')[0].strip()
                    try:
                        duration = float(duration_str)
                    except:
                        duration = 0
                else:
                    duration = 0
                
                results.append({
                    'file': sf,
                    'mode': mode_name,
                    'queue_drain': queue_drain,
                    'avg_queue_wait': avg_queue_wait,
                    'segments': segments,
                    'skipped': skipped,
                    'duration': duration
                })
            except Exception as e:
                pass
    
    if results:
        print("\n*** QUEUE DRAIN TIME = Total end-to-end latency ***")
        print("*** SKIPPED = Translations lost (should be 0) ***\n")
        
        print(f"{'Mode':<18} {'Duration':>8} {'Drain':>8} {'Wait':>8} {'Segments':>10} {'Skipped':>8}")
        print("-" * 70)
        for r in sorted(results, key=lambda x: x['queue_drain'] if x['queue_drain'] else 999):
            drain_str = f"{r['queue_drain']:.1f}s" if r['queue_drain'] else "N/A"
            wait_str = f"{r['avg_queue_wait']:.1f}s" if r['avg_queue_wait'] else "N/A"
            dur_str = f"{r['duration']:.0f}m" if r['duration'] else "N/A"
            skipped_str = str(r['skipped']) if r['skipped'] == 0 else f"{r['skipped']} !!!"
            print(f"{r['mode']:<18} {dur_str:>8} {drain_str:>8} {wait_str:>8} {r['segments']:>10} {skipped_str:>8}")
        
        print("\n" + "-"*70)
        print("Lower Drain Time = Better overall latency")
        print("Skipped should always be 0 (no lost translations)")
    else:
        print("\nCould not parse summary files.")
    
    print("\n" + "-"*70)
    print("Individual summary files:")
    for sf in sorted(summary_files, reverse=True):
        print(f"  - {sf}")
    
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
            print(f"Selected: {source_language[1]}")
            break
        print("Invalid choice.")
    
    # How many output languages?
    print("\nSTEP 2: NUMBER OF OUTPUT LANGUAGES")
    print("-" * 70)
    print("How many languages do you want to translate to?")
    print("  1 - Single language (full screen)")
    print("  2 - Two languages (split screen)")
    print("  3 - Three languages")
    print("  4 - Four languages")
    
    while True:
        num_choice = input("\nEnter number of languages (1-4): ").strip()
        if num_choice in ['1', '2', '3', '4']:
            num_languages = int(num_choice)
            break
        print("Invalid choice. Enter 1, 2, 3, or 4.")
    
    # Output languages
    print(f"\nSTEP 3: SELECT {num_languages} OUTPUT LANGUAGE(S)")
    print("-" * 70)
    for num, (code, name) in OUTPUT_LANGUAGES.items():
        print(f"{num:>2}. {name}")
    
    target_languages = []
    for i in range(num_languages):
        while True:
            choice = input(f"\nSelect output language #{i+1} (1-16): ").strip()
            if choice in OUTPUT_LANGUAGES:
                lang = OUTPUT_LANGUAGES[choice]
                if lang not in target_languages:
                    target_languages.append(lang)
                    print(f"Language {i+1}: {lang[1]}")
                    break
                else:
                    print("Already selected. Choose a different language.")
            else:
                print("Invalid choice.")
    
    print(f"\nConfiguration complete:")
    print(f"  Input: {source_language[1]}")
    print(f"  Output: {', '.join([l[1] for l in target_languages])}")
    
    return source_language, target_languages, target_languages


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    print("="*70)
    print("TEST - SERMON TRANSLATION SYSTEM - TEST HARNESS")
    print("   Instrumented version for latency testing and comparison")
    print("="*70)
    
    # Check for ffmpeg
    if not FFMPEG_AVAILABLE:
        print("\nWARNING:  WARNING: ffmpeg not found - MP3 support disabled")
        print("   Install with: winget install ffmpeg")
        print("   Or download from: https://ffmpeg.org/download.html")
        print("   (WAV files will still work)")
    
    # Select test mode
    test_mode = select_test_mode()
    
    # Select audio source
    audio_source, audio_file_path, playback_speed, max_duration = select_audio_source()
    
    # Configure languages
    source_lang, target_langs, display_langs = configure_languages()
    
    # Confirm
    print("\n" + "="*70)
    print("    TEST CONFIGURATION SUMMARY")
    print("="*70)
    print(f"Test Mode:      {test_mode} - {TEST_MODES[test_mode]['name']}")
    print(f"Audio Source:   {audio_source.upper()}")
    if audio_source == "file":
        print(f"Audio File:     {os.path.basename(audio_file_path)}")
        if max_duration:
            print(f"Duration Limit: {max_duration/60:.0f} minutes")
            effective_time = max_duration / playback_speed / 60
            print(f"Playback Speed: {playback_speed}x (effective test time: ~{effective_time:.1f} min)")
        else:
            print(f"Duration Limit: None (full file)")
            print(f"Playback Speed: {playback_speed}x")
    print(f"Input Language: {source_lang[1]}")
    print(f"Output:         {', '.join([l[1] for l in target_langs])}")
    print("="*70)
    
    if audio_source == "file":
        print("\n📌 NOTE: Test will run automatically and stop when audio completes.")
        print("   Press Ctrl+Shift+R to start, or Ctrl+Shift+S to stop early.")
    
    confirm = input("\nStart test? (Y/n): ").strip().lower()
    if confirm == 'n':
        print("Cancelled.")
        exit(0)
    
    # Create and run system
    system = TestHarnessSystem(
        source_language=source_lang,
        target_languages=target_langs,
        display_languages=display_langs,
        test_mode=test_mode,
        audio_source=audio_source,
        audio_file_path=audio_file_path,
        playback_speed=playback_speed,
        max_duration=max_duration
    )
    
    try:
        system.start()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        system.stop()