"""
Sermon Translation System - PRODUCTION VERSION
===============================================

A GUI-based production application for real-time sermon translation.
Uses Mode 15 (Balanced Quality) settings optimized for congregation use.

Features:
- Clean GUI for easy configuration
- Audio source selection (microphone or file)
- Language configuration (1-4 output languages)
- Configuration summary before starting
- Reset/Clear option to start over
- Congregation display window (F5)

Mode 15 Settings:
- Context-aware translation (2 previous segments)
- Punctuation enabled for better sentence boundaries
- Early interim display for faster perceived response
- Glossary-based term consistency
- Target: 5-15 sec delay with high quality
"""

import pyaudio
import queue
import threading
from typing import Generator, List, Dict, Optional
from google.cloud import speech
from google.cloud import translate_v2 as translate
from google.protobuf import duration_pb2
from google.oauth2 import service_account
from datetime import datetime, timedelta
import os
import warnings
import tkinter as tk
from tkinter import ttk, font, filedialog, messagebox
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

# =============================================================================
# CONFIGURATION
# =============================================================================

# Suppress warnings
os.environ['GRPC_VERBOSITY'] = 'ERROR'
os.environ['GRPC_TRACE'] = ''
warnings.filterwarnings('ignore')

# Credentials path - update this for your setup
CREDENTIALS_PATH = 'credentials/sermon-streaming.json'
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = CREDENTIALS_PATH

# Default audio folder - update for your setup
DEFAULT_AUDIO_FOLDER = r"C:\Users\sermon_translator\AppData\Local\software\projects\sermon_translation\audio"

# Audio parameters
RATE = 16000
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1

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

# =============================================================================
# MODE 15 CONFIGURATION (Production Settings)
# =============================================================================

PRODUCTION_CONFIG = {
    "name": "Production Mode (Balanced Quality)",
    "description": "Context-aware translation with 5-15 sec delay",
    "reading_speed": 220,
    "min_display_time": 2.5,
    "fade_duration": 0.3,
    "buffer_time": 0.5,
    "use_interim_results": False,
    "max_latency": None,
    "catchup_enabled": False,
    "catchup_threshold": None,
    "chunk_split_enabled": True,
    "chunk_split_threshold": 30,
    "chunk_min_size": 10,
    # Recognition settings
    "force_faster_recognition": True,
    "use_short_model": False,
    "use_default_model": True,
    "api_interim_results": True,
    "disable_enhanced": True,
    "disable_punctuation": False,  # ENABLED for better translation
    "disable_speech_context": False,  # Speech hints ENABLED
    "use_voice_activity_timeout": False,
    # Early interim display
    "early_interim_display": True,
    "early_interim_word_threshold": 15,
    # Context-Aware Translation
    "context_aware_translation": True,
    "context_chunks": 2,
    "context_separator": " ",
    "use_bracket_separator": True,
    # Logging
    "save_translation_log": True,
    "run_context_comparison": True,
    # Glossary
    "use_glossary": True,
    "glossary_case_sensitive": False,
    # Reports
    "generate_difference_report": False,
    "generate_glossary_report": True,
    # Audio replay buffer
    "audio_replay_buffer_enabled": True,
    "audio_replay_buffer_seconds": 90,
}

# =============================================================================
# LANGUAGE DEFINITIONS
# =============================================================================

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
# THEOLOGICAL GLOSSARY
# =============================================================================

THEOLOGICAL_GLOSSARY = {
    # Core Theological Terms
    "graça": "grace", "graca": "grace",
    "salvação": "salvation", "salvacao": "salvation",
    "justificação": "justification", "justificacao": "justification",
    "santificação": "sanctification", "santificacao": "sanctification",
    "redenção": "redemption", "redencao": "redemption",
    "arrependimento": "repentance",
    # God / Trinity
    "Trindade": "Trinity",
    "Espírito Santo": "Holy Spirit", "Espirito Santo": "Holy Spirit",
    "Messias": "Messiah", "Cristo": "Christ", "Senhor": "Lord",
    # Biblical Names
    "Pedro": "Peter", "Paulo": "Paul", "Tiago": "James",
    "João": "John", "Joao": "John",
    "Abraão": "Abraham", "Abraao": "Abraham",
    "Moisés": "Moses", "Moises": "Moses",
    "Davi": "David",
    # Church Terms
    "igreja": "church", "batismo": "baptism",
    "congregação": "congregation", "congregacao": "congregation",
    "pastor": "pastor", "evangelho": "gospel",
    # Sin / Salvation
    "pecado": "sin", "cruz": "cross",
    "ressurreição": "resurrection", "ressurreicao": "resurrection",
    "perdão": "forgiveness", "perdao": "forgiveness",
}


# =============================================================================
# SETUP WIZARD GUI
# =============================================================================

class SetupWizard:
    """GUI wizard for configuring the sermon translation system"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Sermon Translation System - Setup")
        self.root.geometry("750x650")
        self.root.minsize(700, 600)  # Minimum size to prevent button cutoff
        self.root.configure(bg='#1a1a2e')
        
        # Configuration storage
        self.config = {
            'audio_source': None,  # 'microphone' or 'file'
            'audio_file': None,
            'duration_limit': None,
            'input_language': None,
            'output_languages': [],
        }
        
        # Current step
        self.current_step = 1
        
        # Create main container
        self.main_frame = tk.Frame(self.root, bg='#1a1a2e')
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Title
        self.title_label = tk.Label(
            self.main_frame,
            text="🎤 Sermon Translation System",
            font=('Arial', 24, 'bold'),
            fg='#00ff88',
            bg='#1a1a2e'
        )
        self.title_label.pack(pady=(0, 10))
        
        self.subtitle_label = tk.Label(
            self.main_frame,
            text="Production Mode - Balanced Quality",
            font=('Arial', 12),
            fg='#888888',
            bg='#1a1a2e'
        )
        self.subtitle_label.pack(pady=(0, 20))
        
        # Step indicator
        self.step_frame = tk.Frame(self.main_frame, bg='#1a1a2e')
        self.step_frame.pack(fill=tk.X, pady=(0, 20))
        
        self.step_labels = []
        steps = ["1. Audio Source", "2. Languages", "3. Summary"]
        for i, step in enumerate(steps):
            lbl = tk.Label(
                self.step_frame,
                text=step,
                font=('Arial', 11, 'bold'),
                fg='#444444',
                bg='#1a1a2e',
                padx=20
            )
            lbl.pack(side=tk.LEFT, expand=True)
            self.step_labels.append(lbl)
        
        # Button frame - PACK FIRST (at bottom) so it's always visible
        self.button_frame = tk.Frame(self.main_frame, bg='#1a1a2e')
        self.button_frame.pack(fill=tk.X, pady=(10, 0), side=tk.BOTTOM)
        
        # Configure grid columns for button layout
        self.button_frame.columnconfigure(0, weight=0)  # Clear button
        self.button_frame.columnconfigure(1, weight=0)  # Back button
        self.button_frame.columnconfigure(2, weight=1)  # Spacer
        self.button_frame.columnconfigure(3, weight=0)  # Next/Start button
        
        self.clear_btn = tk.Button(
            self.button_frame,
            text="🔄 Clear & Restart",
            font=('Arial', 11),
            bg='#555555',
            fg='white',
            activebackground='#666666',
            activeforeground='white',
            command=self.clear_and_restart,
            padx=15,
            pady=8,
            cursor='hand2',
            relief=tk.RAISED,
            bd=2
        )
        self.clear_btn.grid(row=0, column=0, padx=(0, 10), sticky='w')
        
        self.back_btn = tk.Button(
            self.button_frame,
            text="← Back",
            font=('Arial', 11),
            bg='#333366',
            fg='white',
            activebackground='#444477',
            activeforeground='white',
            command=self.go_back,
            padx=15,
            pady=8,
            state=tk.DISABLED,
            cursor='hand2',
            relief=tk.RAISED,
            bd=2
        )
        self.back_btn.grid(row=0, column=1, padx=(0, 10), sticky='w')
        
        self.next_btn = tk.Button(
            self.button_frame,
            text="Next →",
            font=('Arial', 12, 'bold'),
            bg='#00aa66',
            fg='white',
            activebackground='#00cc77',
            activeforeground='white',
            command=self.go_next,
            padx=30,
            pady=10,
            cursor='hand2',
            relief=tk.RAISED,
            bd=2
        )
        self.next_btn.grid(row=0, column=3, sticky='e')
        
        # Content frame (changes based on step) - PACK AFTER buttons
        self.content_frame = tk.Frame(self.main_frame, bg='#0f0f23', relief=tk.RIDGE, bd=2)
        self.content_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        # Show first step
        self.show_step(1)
        
        # Result
        self.result = None
        
    def update_step_indicators(self):
        """Update step indicator colors"""
        for i, lbl in enumerate(self.step_labels):
            if i + 1 < self.current_step:
                lbl.config(fg='#00ff88')  # Completed
            elif i + 1 == self.current_step:
                lbl.config(fg='#ffffff')  # Current
            else:
                lbl.config(fg='#444444')  # Future
    
    def clear_content(self):
        """Clear the content frame"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()
    
    def show_step(self, step):
        """Display the appropriate step"""
        self.current_step = step
        self.update_step_indicators()
        self.clear_content()
        
        # Update buttons
        self.back_btn.config(state=tk.NORMAL if step > 1 else tk.DISABLED)
        
        if step == 1:
            self.show_audio_source_step()
            self.next_btn.config(text="Next →", command=self.go_next)
        elif step == 2:
            self.show_language_step()
            self.next_btn.config(text="Next →", command=self.go_next)
        elif step == 3:
            self.show_summary_step()
            self.next_btn.config(text="▶ START", command=self.start_system)
    
    def show_audio_source_step(self):
        """Step 1: Audio Source Selection"""
        # Title
        tk.Label(
            self.content_frame,
            text="Select Audio Source",
            font=('Arial', 16, 'bold'),
            fg='white',
            bg='#0f0f23'
        ).pack(pady=(20, 20))
        
        # Radio buttons for source type
        self.audio_source_var = tk.StringVar(value=self.config['audio_source'] or 'microphone')
        
        source_frame = tk.Frame(self.content_frame, bg='#0f0f23')
        source_frame.pack(fill=tk.X, padx=40)
        
        # Microphone option
        mic_frame = tk.Frame(source_frame, bg='#1a1a2e', relief=tk.RIDGE, bd=1)
        mic_frame.pack(fill=tk.X, pady=5)
        
        tk.Radiobutton(
            mic_frame,
            text="🎤  Live Microphone",
            variable=self.audio_source_var,
            value='microphone',
            font=('Arial', 14),
            fg='white',
            bg='#1a1a2e',
            selectcolor='#333366',
            activebackground='#1a1a2e',
            activeforeground='white',
            command=self.on_source_change
        ).pack(anchor=tk.W, padx=20, pady=15)
        
        tk.Label(
            mic_frame,
            text="Use USB microphone or audio interface for live translation",
            font=('Arial', 10),
            fg='#888888',
            bg='#1a1a2e'
        ).pack(anchor=tk.W, padx=45, pady=(0, 15))
        
        # File option
        file_frame = tk.Frame(source_frame, bg='#1a1a2e', relief=tk.RIDGE, bd=1)
        file_frame.pack(fill=tk.X, pady=5)
        
        tk.Radiobutton(
            file_frame,
            text="📁  Audio File (MP3/WAV)",
            variable=self.audio_source_var,
            value='file',
            font=('Arial', 14),
            fg='white',
            bg='#1a1a2e',
            selectcolor='#333366',
            activebackground='#1a1a2e',
            activeforeground='white',
            command=self.on_source_change
        ).pack(anchor=tk.W, padx=20, pady=15)
        
        # File selection sub-frame
        self.file_select_frame = tk.Frame(file_frame, bg='#1a1a2e')
        self.file_select_frame.pack(fill=tk.X, padx=45, pady=(0, 15))
        
        self.file_label = tk.Label(
            self.file_select_frame,
            text="No file selected",
            font=('Arial', 10),
            fg='#888888',
            bg='#1a1a2e'
        )
        self.file_label.pack(side=tk.LEFT)
        
        self.browse_btn = tk.Button(
            self.file_select_frame,
            text="Browse...",
            font=('Arial', 10),
            command=self.browse_file
        )
        self.browse_btn.pack(side=tk.RIGHT, padx=10)
        
        # Duration frame (for file only)
        self.duration_frame = tk.Frame(file_frame, bg='#1a1a2e')
        self.duration_frame.pack(fill=tk.X, padx=45, pady=(0, 15))
        
        tk.Label(
            self.duration_frame,
            text="Duration limit:",
            font=('Arial', 10),
            fg='#aaaaaa',
            bg='#1a1a2e'
        ).pack(side=tk.LEFT)
        
        self.duration_var = tk.StringVar(value='full')
        duration_options = [
            ('Full file', 'full'),
            ('15 minutes', '15'),
            ('30 minutes', '30'),
            ('45 minutes', '45'),
            ('60 minutes', '60'),
        ]
        
        self.duration_combo = ttk.Combobox(
            self.duration_frame,
            textvariable=self.duration_var,
            values=[opt[0] for opt in duration_options],
            state='readonly',
            width=15
        )
        self.duration_combo.set('Full file')
        self.duration_combo.pack(side=tk.LEFT, padx=10)
        
        # Update visibility based on current selection
        self.on_source_change()
        
        # Restore previous selection if any
        if self.config['audio_file']:
            self.file_label.config(text=os.path.basename(self.config['audio_file']))
    
    def on_source_change(self):
        """Handle audio source type change"""
        if self.audio_source_var.get() == 'file':
            self.browse_btn.config(state=tk.NORMAL)
            self.duration_combo.config(state='readonly')
        else:
            self.browse_btn.config(state=tk.DISABLED)
            self.duration_combo.config(state=tk.DISABLED)
    
    def browse_file(self):
        """Open file browser for audio file selection"""
        initial_dir = DEFAULT_AUDIO_FOLDER if os.path.exists(DEFAULT_AUDIO_FOLDER) else os.path.expanduser("~")
        
        file_path = filedialog.askopenfilename(
            title="Select Audio File",
            initialdir=initial_dir,
            filetypes=[
                ("Audio files", "*.mp3 *.wav"),
                ("MP3 files", "*.mp3"),
                ("WAV files", "*.wav"),
            ]
        )
        
        if file_path:
            self.config['audio_file'] = file_path
            self.file_label.config(text=os.path.basename(file_path))
    
    def show_language_step(self):
        """Step 2: Language Configuration"""
        # Create scrollable frame
        canvas = tk.Canvas(self.content_frame, bg='#0f0f23', highlightthickness=0)
        scrollbar = ttk.Scrollbar(self.content_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='#0f0f23')
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Input Language Section
        tk.Label(
            scrollable_frame,
            text="Input Language (what is being spoken)",
            font=('Arial', 14, 'bold'),
            fg='white',
            bg='#0f0f23'
        ).pack(pady=(20, 10), padx=20, anchor=tk.W)
        
        self.input_lang_var = tk.StringVar(value='3')  # Default: Portuguese (Brazil)
        
        input_frame = tk.Frame(scrollable_frame, bg='#1a1a2e')
        input_frame.pack(fill=tk.X, padx=20, pady=5)
        
        # Create grid of input languages
        row = 0
        col = 0
        for key, (code, name) in INPUT_LANGUAGES.items():
            rb = tk.Radiobutton(
                input_frame,
                text=name,
                variable=self.input_lang_var,
                value=key,
                font=('Arial', 11),
                fg='white',
                bg='#1a1a2e',
                selectcolor='#333366',
                activebackground='#1a1a2e',
                activeforeground='white',
                width=22,
                anchor=tk.W
            )
            rb.grid(row=row, column=col, sticky=tk.W, padx=10, pady=3)
            col += 1
            if col >= 3:
                col = 0
                row += 1
        
        # Restore previous selection
        if self.config['input_language']:
            for key, val in INPUT_LANGUAGES.items():
                if val == self.config['input_language']:
                    self.input_lang_var.set(key)
                    break
        
        # Output Languages Section
        tk.Label(
            scrollable_frame,
            text="Output Languages (select 1-4)",
            font=('Arial', 14, 'bold'),
            fg='white',
            bg='#0f0f23'
        ).pack(pady=(30, 10), padx=20, anchor=tk.W)
        
        self.output_lang_vars = {}
        
        output_frame = tk.Frame(scrollable_frame, bg='#1a1a2e')
        output_frame.pack(fill=tk.X, padx=20, pady=5)
        
        # Create grid of output languages
        row = 0
        col = 0
        for key, (code, name) in OUTPUT_LANGUAGES.items():
            var = tk.BooleanVar(value=False)
            self.output_lang_vars[key] = var
            
            # Restore previous selection
            if self.config['output_languages']:
                for lang in self.config['output_languages']:
                    if lang == OUTPUT_LANGUAGES[key]:
                        var.set(True)
            
            cb = tk.Checkbutton(
                output_frame,
                text=name,
                variable=var,
                font=('Arial', 11),
                fg='white',
                bg='#1a1a2e',
                selectcolor='#333366',
                activebackground='#1a1a2e',
                activeforeground='white',
                width=22,
                anchor=tk.W
            )
            cb.grid(row=row, column=col, sticky=tk.W, padx=10, pady=3)
            col += 1
            if col >= 3:
                col = 0
                row += 1
        
        # Default: English (US) selected if nothing selected
        if not self.config['output_languages']:
            self.output_lang_vars['8'].set(True)  # English (US)
        
        # Pack canvas and scrollbar
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def show_summary_step(self):
        """Step 3: Configuration Summary"""
        tk.Label(
            self.content_frame,
            text="Configuration Summary",
            font=('Arial', 16, 'bold'),
            fg='white',
            bg='#0f0f23'
        ).pack(pady=(20, 20))
        
        summary_frame = tk.Frame(self.content_frame, bg='#1a1a2e', relief=tk.RIDGE, bd=1)
        summary_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=10)
        
        # Audio Source
        audio_text = "🎤 Live Microphone"
        if self.config['audio_source'] == 'file':
            filename = os.path.basename(self.config['audio_file']) if self.config['audio_file'] else "No file"
            duration = self.config.get('duration_limit', 'Full file')
            if duration:
                duration_text = f"{duration} minutes" if duration != 'full' else "Full file"
            else:
                duration_text = "Full file"
            audio_text = f"📁 Audio File: {filename}\n     Duration: {duration_text}"
        
        self._add_summary_row(summary_frame, "Audio Source", audio_text, 0)
        
        # Input Language
        input_lang = self.config['input_language']
        input_text = input_lang[1] if input_lang else "Not selected"
        self._add_summary_row(summary_frame, "Input Language", input_text, 1)
        
        # Output Languages
        output_langs = self.config['output_languages']
        output_text = ", ".join([lang[1] for lang in output_langs]) if output_langs else "Not selected"
        self._add_summary_row(summary_frame, "Output Languages", output_text, 2)
        
        # Mode info
        self._add_summary_row(summary_frame, "Translation Mode", "Balanced Quality (Context-Aware)", 3)
        self._add_summary_row(summary_frame, "Expected Latency", "5-15 seconds", 4)
        
        # Instructions - Compact single line format for keyboard controls
        instructions_frame = tk.Frame(self.content_frame, bg='#0f0f23')
        instructions_frame.pack(fill=tk.X, padx=40, pady=(15, 10))
        
        tk.Label(
            instructions_frame,
            text="📌 Keyboard Controls:",
            font=('Arial', 12, 'bold'),
            fg='#ffcc00',
            bg='#0f0f23'
        ).pack(anchor=tk.W, pady=(0, 5))
        
        # Line 1: Window controls
        tk.Label(
            instructions_frame,
            text="   F5 = Congregation Window  |  F11 = Fullscreen",
            font=('Arial', 11),
            fg='#aaaaaa',
            bg='#0f0f23'
        ).pack(anchor=tk.W, pady=2)
        
        # Line 2: System controls (grouped by Ctrl+Shift)
        tk.Label(
            instructions_frame,
            text="   Ctrl+Shift:  R = START,  S = STOP,  Q = QUIT",
            font=('Arial', 11),
            fg='#aaaaaa',
            bg='#0f0f23'
        ).pack(anchor=tk.W, pady=2)
    
    def _add_summary_row(self, parent, label, value, row):
        """Add a row to the summary"""
        frame = tk.Frame(parent, bg='#1a1a2e')
        frame.pack(fill=tk.X, padx=20, pady=8)
        
        tk.Label(
            frame,
            text=f"{label}:",
            font=('Arial', 12, 'bold'),
            fg='#00ff88',
            bg='#1a1a2e',
            width=18,
            anchor=tk.W
        ).pack(side=tk.LEFT)
        
        tk.Label(
            frame,
            text=value,
            font=('Arial', 12),
            fg='white',
            bg='#1a1a2e',
            anchor=tk.W
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
    
    def validate_step(self, step):
        """Validate current step before proceeding"""
        if step == 1:
            self.config['audio_source'] = self.audio_source_var.get()
            
            if self.config['audio_source'] == 'file':
                if not self.config['audio_file'] or not os.path.exists(self.config['audio_file']):
                    messagebox.showerror("Error", "Please select a valid audio file.")
                    return False
                
                # Get duration limit
                duration_text = self.duration_combo.get()
                if duration_text == 'Full file':
                    self.config['duration_limit'] = None
                else:
                    self.config['duration_limit'] = int(duration_text.split()[0])
            
            return True
        
        elif step == 2:
            # Get input language
            input_key = self.input_lang_var.get()
            self.config['input_language'] = INPUT_LANGUAGES[input_key]
            
            # Get output languages
            self.config['output_languages'] = []
            for key, var in self.output_lang_vars.items():
                if var.get():
                    self.config['output_languages'].append(OUTPUT_LANGUAGES[key])
            
            if not self.config['output_languages']:
                messagebox.showerror("Error", "Please select at least one output language.")
                return False
            
            if len(self.config['output_languages']) > 4:
                messagebox.showerror("Error", "Maximum 4 output languages allowed.")
                return False
            
            return True
        
        return True
    
    def go_next(self):
        """Go to next step"""
        if self.validate_step(self.current_step):
            self.show_step(self.current_step + 1)
    
    def go_back(self):
        """Go to previous step"""
        if self.current_step > 1:
            self.show_step(self.current_step - 1)
    
    def clear_and_restart(self):
        """Clear all selections and restart from step 1"""
        if messagebox.askyesno("Clear Configuration", "Are you sure you want to clear all selections and start over?"):
            self.config = {
                'audio_source': None,
                'audio_file': None,
                'duration_limit': None,
                'input_language': None,
                'output_languages': [],
            }
            self.show_step(1)
    
    def start_system(self):
        """Validate and start the translation system"""
        self.result = self.config.copy()
        self.root.quit()
        self.root.destroy()
    
    def run(self):
        """Run the setup wizard and return configuration"""
        self.root.mainloop()
        return self.result


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main entry point for production system"""
    print("=" * 70)
    print("  SERMON TRANSLATION SYSTEM - PRODUCTION")
    print("  Mode: Balanced Quality (Context-Aware)")
    print("=" * 70)
    
    # Check for ffmpeg
    if not FFMPEG_AVAILABLE:
        print("\n⚠️  WARNING: ffmpeg not found - MP3 support may be limited")
        print("   Install with: winget install ffmpeg")
    
    # Check for credentials
    if not os.path.exists(CREDENTIALS_PATH):
        print(f"\n❌ ERROR: Credentials file not found: {CREDENTIALS_PATH}")
        print("   Please ensure your Google Cloud credentials are properly configured.")
        input("\nPress Enter to exit...")
        return
    
    # Run setup wizard
    wizard = SetupWizard()
    config = wizard.run()
    
    if not config:
        print("\nSetup cancelled.")
        return
    
    print("\n" + "=" * 70)
    print("  STARTING TRANSLATION SYSTEM")
    print("=" * 70)
    print(f"\nAudio Source: {config['audio_source']}")
    if config['audio_source'] == 'file':
        print(f"Audio File: {config['audio_file']}")
        print(f"Duration Limit: {config['duration_limit'] or 'Full file'}")
    print(f"Input Language: {config['input_language'][1]}")
    print(f"Output Languages: {', '.join([l[1] for l in config['output_languages']])}")
    print("=" * 70)
    
    # Import and run the main system
    # This assumes the test harness module is available
    try:
        # Try to import from the test harness
        from sermon_translation_test_harness import TestHarnessSystem, TEST_MODES
        
        # Prepare parameters
        source_lang = config['input_language']
        target_langs = config['output_languages']
        display_langs = config['output_languages']
        
        audio_source = config['audio_source']
        audio_file = config['audio_file']
        max_duration = config['duration_limit'] * 60 if config['duration_limit'] else None
        
        # Create and run system with Mode 15
        system = TestHarnessSystem(
            source_language=source_lang,
            target_languages=target_langs,
            display_languages=display_langs,
            test_mode=15,  # Mode 15: Balanced Quality
            audio_source=audio_source,
            audio_file_path=audio_file,
            playback_speed=1.0,
            max_duration=max_duration
        )
        
        print("\n📌 KEYBOARD CONTROLS:")
        print("   F5           = Open/Close Congregation Display")
        print("   Ctrl+Shift+R = START translation")
        print("   Ctrl+Shift+S = STOP translation")
        print("   Ctrl+Shift+Q = QUIT application")
        
        system.start()
        
    except ImportError as e:
        print(f"\n❌ ERROR: Could not import translation system: {e}")
        print("   Make sure sermon_translation_test_harness.py is in the same directory.")
        input("\nPress Enter to exit...")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()