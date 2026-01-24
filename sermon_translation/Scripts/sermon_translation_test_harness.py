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
from google.protobuf import duration_pb2
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
        "description": "Splits long segments (30+ words) for consistent display timing",
        "reading_speed": 220,  # Comfortable reading speed
        "min_display_time": 2.5,  # Optimized
        "fade_duration": 0.3,  # Quick fades
        "buffer_time": 0.5,  # Optimized
        "use_interim_results": False,
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": True,
        "chunk_split_threshold": 30,  # Max words per chunk
        "chunk_min_size": 10,  # Minimum words in a chunk
    },
    8: {
        "name": "Fast Recognition + Splitting",
        "description": "Forces faster Google recognition + chunk splitting (best for Portuguese)",
        "reading_speed": 220,  # Comfortable reading speed
        "min_display_time": 2.5,  # Optimized
        "fade_duration": 0.3,  # Quick fades
        "buffer_time": 0.5,  # Optimized
        "use_interim_results": False,  # Don't display interim to congregation
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": True,
        "chunk_split_threshold": 30,  # Max words per chunk (reduced from 40)
        "chunk_min_size": 10,  # Minimum words in a chunk (reduced from 15)
        # Fast recognition settings
        "force_faster_recognition": True,
        "use_short_model": True,  # Use "latest_short" instead of "latest_long"
        "api_interim_results": True,  # Enable interim at API level (forces faster processing)
    },
    9: {
        "name": "High Accuracy + Splitting",
        "description": "Maximum accuracy (latest_long) + faster returns + chunk splitting",
        "reading_speed": 220,  # Comfortable reading speed
        "min_display_time": 2.5,  # Optimized
        "fade_duration": 0.3,  # Quick fades
        "buffer_time": 0.5,  # Optimized
        "use_interim_results": False,  # Don't display interim to congregation
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": True,
        "chunk_split_threshold": 30,  # Max words per chunk
        "chunk_min_size": 10,  # Minimum words in a chunk
        # High accuracy settings
        "force_faster_recognition": True,
        "use_short_model": False,  # Use "latest_long" for better accuracy
        "api_interim_results": True,  # Enable interim at API level (faster returns)
    },
    10: {
        "name": "Minimal Latency (Portuguese)",
        "description": "Stripped-down settings for fastest recognition - best for Portuguese",
        "reading_speed": 220,  # Comfortable reading speed
        "min_display_time": 2.5,  # Optimized
        "fade_duration": 0.3,  # Quick fades
        "buffer_time": 0.5,  # Optimized
        "use_interim_results": False,  # Don't display interim to congregation
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": True,
        "chunk_split_threshold": 30,  # Max words per chunk
        "chunk_min_size": 10,  # Minimum words in a chunk
        # Minimal latency settings - strip everything that causes delay
        "force_faster_recognition": True,
        "use_short_model": False,  # Use default model
        "use_default_model": True,  # Flag to use "default" instead of latest_long
        "api_interim_results": True,  # Enable interim at API level
        "disable_enhanced": True,  # Don't use enhanced model
        "disable_punctuation": True,  # Don't wait for punctuation
        "disable_speech_context": True,  # No sermon hints (may cause buffering)
    },
    11: {
        "name": "Voice Activity Timeout",
        "description": "Mode 10 settings (voice_activity_timeout disabled - caused stream issues)",
        "reading_speed": 220,  # Comfortable reading speed
        "min_display_time": 2.5,  # Optimized
        "fade_duration": 0.3,  # Quick fades
        "buffer_time": 0.5,  # Optimized
        "use_interim_results": False,  # Don't display interim to congregation
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": True,
        "chunk_split_threshold": 30,  # Max words per chunk
        "chunk_min_size": 10,  # Minimum words in a chunk
        # Minimal latency settings (same as Mode 10)
        "force_faster_recognition": True,
        "use_short_model": False,
        "use_default_model": True,
        "api_interim_results": True,
        "disable_enhanced": True,
        "disable_punctuation": True,
        "disable_speech_context": True,
        # Voice activity timeout - DISABLED (causes stream restarts)
        "use_voice_activity_timeout": False,
        "speech_start_timeout_sec": 10,
        "speech_end_timeout_sec": 3,
    },
    12: {
        "name": "Early Interim Display",
        "description": "Display interim results after 15 words - don't wait for FINAL",
        "reading_speed": 220,  # Comfortable reading speed
        "min_display_time": 2.5,  # Optimized
        "fade_duration": 0.3,  # Quick fades
        "buffer_time": 0.5,  # Optimized
        "use_interim_results": False,  # Standard interim display OFF
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": True,
        "chunk_split_threshold": 30,  # Max words per chunk
        "chunk_min_size": 10,  # Minimum words in a chunk
        # Minimal latency settings (same as Mode 10)
        "force_faster_recognition": True,
        "use_short_model": False,
        "use_default_model": True,
        "api_interim_results": True,  # Must be True to receive interim results
        "disable_enhanced": True,
        "disable_punctuation": True,
        "disable_speech_context": False,  # ENABLED - helps with theological terms (Option C)
        "use_voice_activity_timeout": False,
        # Early interim display settings - KEY FEATURE
        "early_interim_display": True,
        "early_interim_word_threshold": 15,  # Display interim after this many words (reduced from 20)
        # Context-aware translation settings (NEW)
        "save_translation_log": True,        # Save PT/EN pairs for review (NO latency impact)
        "run_context_comparison": True,      # Run end-of-test context comparison (NO latency impact)
        "context_aware_translation": False,  # DISABLED - causes significant latency (~500ms per chunk)
        "context_chunks": 1,                 # How many previous chunks to include (1-3)
    },
    13: {
        "name": "Context-Enhanced (Experimental)",
        "description": "Mode 12 + Glossary consistency + Async context comparison",
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
        # Minimal latency settings
        "force_faster_recognition": True,
        "use_short_model": False,
        "use_default_model": True,
        "api_interim_results": True,
        "disable_enhanced": True,
        "disable_punctuation": True,
        "disable_speech_context": False,
        "use_voice_activity_timeout": False,
        # Early interim display settings
        "early_interim_display": True,
        "early_interim_word_threshold": 15,
        # Logging (inherited from Mode 12)
        "save_translation_log": True,
        "run_context_comparison": True,
        "context_aware_translation": False,  # Keep disabled for real-time path
        "context_chunks": 1,
        # === NEW MODE 13 FEATURES ===
        # Option A: Async Context Comparison (background thread)
        "async_context_comparison": True,    # Compare fast vs context in background
        "async_context_threads": 2,          # Number of background workers
        "flag_pronoun_differences": True,    # Flag he/she/it changes
        "min_difference_threshold": 0.15,    # Min word difference ratio to flag (0-1)
        # Option B: Glossary Lookup
        "use_glossary": True,                # Apply theological term consistency
        "glossary_case_sensitive": False,    # Match regardless of case
        # Output files
        "generate_difference_report": True,  # *_context_differences.txt
        "generate_glossary_report": True,    # *_glossary_corrections.txt
    },
    14: {
        "name": "Context-Aware Quality (Native Speaker Approved)",
        "description": "RECOMMENDED: Full context translation for accurate, readable output. ~10-20 sec delay but significantly better quality. Uses 5 previous segments as context to help Google Translate understand pronouns, flow, and fill gaps from imperfect speech recognition.",
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
        # Recognition settings (same as Mode 12)
        "force_faster_recognition": True,
        "use_short_model": False,
        "use_default_model": True,
        "api_interim_results": True,
        "disable_enhanced": True,
        "disable_punctuation": True,
        "disable_speech_context": False,  # Speech hints ENABLED
        "use_voice_activity_timeout": False,
        # Early interim display - DISABLED for quality mode
        # We wait for FINAL results to ensure complete sentences
        "early_interim_display": False,
        "early_interim_word_threshold": 15,
        # === KEY FEATURE: Context-Aware Translation ===
        "context_aware_translation": True,   # ENABLED - sends previous segments as context
        "context_chunks": 5,                 # LARGE: 5 previous segments for best quality
        "context_separator": " ",            # How to join context segments
        # Logging and comparison
        "save_translation_log": True,
        "run_context_comparison": True,
        # Glossary (from Mode 13)
        "use_glossary": True,
        "glossary_case_sensitive": False,
        # Quality reporting
        "generate_difference_report": False,  # Not needed - we're using context
        "generate_glossary_report": True,
    },
    15: {
        "name": "Balanced Quality (Context + Speed)",
        "description": "HYBRID: Uses 2 previous segments for context. Punctuation ENABLED for better sentence boundaries. Post-recognition corrections fix common errors. Target: 5-15 sec delay with improved quality.",
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
        "disable_punctuation": False,  # ENABLED - adds periods, commas for better translation
        "disable_speech_context": False,  # Speech hints ENABLED
        "use_voice_activity_timeout": False,
        # Early interim display - ENABLED for faster perceived response
        "early_interim_display": True,
        "early_interim_word_threshold": 15,
        # === BALANCED Context-Aware Translation ===
        "context_aware_translation": True,   # ENABLED
        "context_chunks": 2,                 # SMALLER: 2 segments (faster than 5)
        "context_separator": " ",
        "use_bracket_separator": True,       # Use [[[...]]] instead of |||
        # Logging and comparison
        "save_translation_log": True,
        "run_context_comparison": True,
        # Glossary
        "use_glossary": True,
        "glossary_case_sensitive": False,
        # Quality reporting
        "generate_difference_report": False,
        "generate_glossary_report": True,
    },
    16: {
        "name": "Overlap Coverage (Primary-Backup)",
        "description": "PRIMARY/BACKUP MODEL: Stream A outputs directly, Stream B buffers and only releases during Stream A's restart gaps. Eliminates duplicates while maintaining ~99% coverage.",
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
        # Recognition settings (same as Mode 15)
        "force_faster_recognition": True,
        "use_short_model": False,
        "use_default_model": True,
        "api_interim_results": True,
        "disable_enhanced": True,
        "disable_punctuation": False,  # Punctuation ENABLED
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
        # Logging and comparison
        "save_translation_log": True,
        "run_context_comparison": True,
        # Glossary
        "use_glossary": True,
        "glossary_case_sensitive": False,
        # Quality reporting
        "generate_difference_report": False,
        "generate_glossary_report": True,
        # === DUAL STREAM SETTINGS (NEW) ===
        "dual_stream_enabled": True,
        "stream_b_delay_seconds": 150,  # 2.5 minutes offset
        "dedup_similarity_threshold": 0.75,  # Not used in Primary/Backup model
        "dedup_time_window_seconds": 20,  # Not used in Primary/Backup model
        # === PRIMARY/BACKUP MODEL SETTINGS ===
        "gap_threshold_seconds": 3.0,  # Seconds without Stream A output to trigger backup
        "buffer_duration_seconds": 30.0,  # How many seconds of Stream B content to buffer
    },
    17: {
        "name": "Enhanced Context Quality",
        "description": "HYBRID BUFFER: Waits for sentence end OR 50 words OR 15 sec timeout before translating. Targets 90%+ context similarity with 5-15 sec latency.",
        "reading_speed": 220,
        "min_display_time": 2.5,
        "fade_duration": 0.3,
        "buffer_time": 0.5,
        "use_interim_results": False,
        "max_latency": None,
        "catchup_enabled": False,
        "catchup_threshold": None,
        "chunk_split_enabled": True,
        "chunk_split_threshold": 50,  # Larger chunks for buffered content
        "chunk_min_size": 15,         # Minimum chunk size
        # Recognition settings
        "force_faster_recognition": True,
        "use_short_model": False,
        "use_default_model": True,
        "api_interim_results": True,
        "disable_enhanced": True,
        "disable_punctuation": False,  # ENABLED - adds periods, commas for better translation
        "disable_speech_context": False,  # Speech hints ENABLED
        "use_voice_activity_timeout": False,
        # Early interim display - DISABLED for hybrid buffer mode
        "early_interim_display": False,  # Disabled - using hybrid buffer instead
        "early_interim_word_threshold": 20,
        # === HYBRID BUFFER SETTINGS (NEW) ===
        "hybrid_buffer_enabled": True,       # Enable hybrid buffering
        "buffer_sentence_endings": True,     # Trigger on . ? !
        "buffer_max_words": 50,              # Trigger at 50 words
        "buffer_timeout_seconds": 15,        # Safety timeout (max latency)
        # === ENHANCED Context-Aware Translation ===
        "context_aware_translation": True,   # ENABLED
        "context_chunks": 3,                 # Use 3 previous segments for context
        "context_separator": " ",
        "use_bracket_separator": True,       # Use [[[...]]] instead of |||
        # Logging and comparison
        "save_translation_log": True,
        "run_context_comparison": True,
        # Glossary
        "use_glossary": True,
        "glossary_case_sensitive": False,
        # Quality reporting
        "generate_difference_report": False,
        "generate_glossary_report": True,
    },
}

# =============================================================================
# THEOLOGICAL GLOSSARY (Portuguese -> English)
# =============================================================================
# This ensures consistent translation of theological terms across all chunks

THEOLOGICAL_GLOSSARY = {
    # === Core Theological Terms ===
    "graça": "grace",
    "graca": "grace",
    "salvação": "salvation",
    "salvacao": "salvation",
    "justificação": "justification",
    "justificacao": "justification",
    "santificação": "sanctification",
    "santificacao": "sanctification",
    "redenção": "redemption",
    "redencao": "redemption",
    "propiciação": "propitiation",
    "propiciacao": "propitiation",
    "expiação": "atonement",
    "expiacao": "atonement",
    "reconciliação": "reconciliation",
    "reconciliacao": "reconciliation",
    "regeneração": "regeneration",
    "regeneracao": "regeneration",
    "glorificação": "glorification",
    "glorificacao": "glorification",
    "eleição": "election",
    "eleicao": "election",
    "predestinação": "predestination",
    "predestinacao": "predestination",
    "arrependimento": "repentance",
    "conversão": "conversion",
    "conversao": "conversion",
    
    # === God / Trinity ===
    "Trindade": "Trinity",
    "Espírito Santo": "Holy Spirit",
    "Espirito Santo": "Holy Spirit",
    "Consolador": "Comforter",
    "Parácleto": "Paraclete",
    "Paracleto": "Paraclete",
    "Messias": "Messiah",
    "Cristo": "Christ",
    "Senhor": "Lord",
    "Cordeiro de Deus": "Lamb of God",
    "Filho do Homem": "Son of Man",
    "Filho de Deus": "Son of God",
    
    # === Biblical People (ensure consistent naming) ===
    "Pedro": "Peter",
    "Paulo": "Paul",
    "Tiago": "James",
    "João": "John",
    "Joao": "John",
    "Mateus": "Matthew",
    "Marcos": "Mark",
    "Lucas": "Luke",
    "Abraão": "Abraham",
    "Abraao": "Abraham",
    "Isaque": "Isaac",
    "Jacó": "Jacob",
    "Jaco": "Jacob",
    "Moisés": "Moses",
    "Moises": "Moses",
    "Davi": "David",
    "Salomão": "Solomon",
    "Salomao": "Solomon",
    "Elias": "Elijah",
    "Eliseu": "Elisha",
    "Isaías": "Isaiah",
    "Isaias": "Isaiah",
    "Jeremias": "Jeremiah",
    "Ezequiel": "Ezekiel",
    "Daniel": "Daniel",
    "Timóteo": "Timothy",
    "Timoteo": "Timothy",
    "Barnabé": "Barnabas",
    "Barnabe": "Barnabas",
    "Estêvão": "Stephen",
    "Estevao": "Stephen",
    "Nicodemos": "Nicodemus",
    "Zaqueu": "Zacchaeus",
    "Lázaro": "Lazarus",
    "Lazaro": "Lazarus",
    
    # === Places ===
    "Jerusalém": "Jerusalem",
    "Jerusalem": "Jerusalem",
    "Gólgota": "Golgotha",
    "Golgota": "Golgotha",
    "Calvário": "Calvary",
    "Calvario": "Calvary",
    "Getsêmani": "Gethsemane",
    "Getsemani": "Gethsemane",
    "Galileia": "Galilee",
    "Galileia": "Galilee",
    "Judeia": "Judea",
    "Judéia": "Judea",
    "Samaria": "Samaria",
    
    # === Church Terms ===
    "igreja": "church",
    "batismo": "baptism",
    "ceia do Senhor": "Lord's Supper",
    "santa ceia": "Holy Communion",
    "comunhão": "communion",
    "comunhao": "communion",
    "congregação": "congregation",
    "congregacao": "congregation",
    "presbítero": "elder",
    "presbitero": "elder",
    "diácono": "deacon",
    "diacono": "deacon",
    "pastor": "pastor",
    "bispo": "bishop",
    "apóstolo": "apostle",
    "apostolo": "apostle",
    "discípulo": "disciple",
    "discipulo": "disciple",
    "fariseus": "Pharisees",
    "saduceus": "Sadducees",
    "escribas": "scribes",
    
    # === Scripture Terms ===
    "Escrituras": "Scriptures",
    "evangelho": "gospel",
    "epístola": "epistle",
    "epistola": "epistle",
    "parábola": "parable",
    "parabola": "parable",
    "profecia": "prophecy",
    "apocalipse": "Revelation",
    "Apocalipse": "Revelation",
    
    # === Sin / Salvation ===
    "pecado": "sin",
    "pecador": "sinner",
    "transgressão": "transgression",
    "transgressao": "transgression",
    "iniquidade": "iniquity",
    "cruz": "cross",
    "ressurreição": "resurrection",
    "ressurreicao": "resurrection",
    "vida eterna": "eternal life",
    "perdão": "forgiveness",
    "perdao": "forgiveness",
    "misericórdia": "mercy",
    "misericordia": "mercy",
}

# Reverse glossary for detecting if Google used different terms
GLOSSARY_ENGLISH_VARIANTS = {
    "grace": ["grace", "favor", "blessing"],
    "justification": ["justification", "vindication", "acquittal"],
    "propitiation": ["propitiation", "atonement", "expiation"],
    "Holy Spirit": ["Holy Spirit", "Holy Ghost"],
    "church": ["church", "congregation", "assembly"],
    "elder": ["elder", "presbyter", "older"],
    "repentance": ["repentance", "regret", "remorse"],
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
        self.is_hard_paused = False  # Hard pause = full stop
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
    
    def set_paused(self, paused, hard=False):
        """Update pause state with visual indicator
        
        Args:
            paused: Whether paused
            hard: If True, this is a hard pause (full stop)
        """
        self.is_paused = paused
        self.is_hard_paused = hard if paused else False
        
        if paused:
            if hard:
                self.status_bar.config(
                    text="⏹️ STOPPED - No API calls - Ctrl+Shift+R to resume fresh", 
                    bg='#cc0000'  # Dark red
                )
            else:
                self.status_bar.config(
                    text="⏸️ PAUSED - Queue building - Ctrl+Shift+R to resume | Ctrl+Shift+X to stop", 
                    bg='orange'
                )
        else:
            self.status_bar.config(
                text="🟢 ACTIVE - Ctrl+Shift+P to pause | Ctrl+Shift+X to stop", 
                bg='green'
            )
    
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
# DUAL STREAM MANAGER - For Overlap Coverage (Mode 16)
# PRIMARY/BACKUP MODEL: Stream A is primary, Stream B fills gaps during restarts
# =============================================================================

from enum import Enum

class StreamRole(Enum):
    PRIMARY = "primary"      # Outputs to display
    BACKUP = "backup"        # Buffers content, only outputs during primary's gaps
    RESTARTING = "restarting"  # Currently restarting


class DualStreamManager:
    """
    Manages two overlapping speech recognition streams using PRIMARY/BACKUP model.
    
    - Stream A = PRIMARY: Always outputs content to display
    - Stream B = BACKUP: Buffers content, only releases during Stream A's restart gaps
    
    This eliminates duplicates while maintaining gap coverage.
    
    Timeline:
         0:00    2:30    5:00    5:05    7:30    10:00   10:05
           │       │       │       │       │       │       │
    Stream A:  ████████████████|GAP|████████████████████|GAP|████████
               PRIMARY         restart                   restart
                                 │                         │
    Stream B:       ████████████|███|███████████████████|███|████████
                    BACKUP      OUTPUT                  OUTPUT
                   (buffering) (fill gap)             (fill gap)
    """
    
    def __init__(self, speech_client, config, streaming_config, audio_streamer,
                 stream_b_delay: float = 150, gap_threshold: float = 3.0,
                 buffer_duration: float = 30.0):
        """
        Initialize dual stream manager with Primary/Backup model.
        
        Args:
            speech_client: Google Speech client
            config: Recognition config
            streaming_config: Streaming recognition config
            audio_streamer: Audio source (file or microphone)
            stream_b_delay: Seconds to delay Stream B start (default 2.5 min)
            gap_threshold: Seconds without Stream A output to trigger backup (default 3s)
            buffer_duration: How many seconds of Stream B content to buffer (default 30s)
        """
        self.speech_client = speech_client
        self.config = config
        self.streaming_config = streaming_config
        self.audio_streamer = audio_streamer
        
        self.stream_b_delay = stream_b_delay
        self.gap_threshold = gap_threshold
        self.buffer_duration = buffer_duration
        
        # Stream roles
        self.stream_a_role = StreamRole.PRIMARY
        self.stream_b_role = StreamRole.BACKUP
        
        # Stream state
        self.stream_a_active = False
        self.stream_b_active = False
        self.stream_b_started = False
        
        # SEPARATE audio queues for each stream
        self.stream_a_queue = queue.Queue()
        self.stream_b_queue = queue.Queue()
        
        # Stream B buffer (holds content while backing up)
        self.stream_b_buffer = []  # List of (timestamp, transcript) tuples
        self.buffer_lock = threading.Lock()
        
        # Last output tracking for gap detection
        self.last_stream_a_output = None
        self.stream_a_restarting = False
        
        # Results queue (thread-safe) - final output to display
        self.results_queue = queue.Queue()
        
        # Statistics
        self.stream_a_segments = 0
        self.stream_b_segments = 0
        self.stream_b_segments_buffered = 0  # Total buffered (not output)
        self.stream_b_segments_released = 0  # Released during gaps
        self.gaps_filled = 0  # Number of gaps filled by Stream B
        self.stream_a_restarts = 0
        self.stream_b_restarts = 0
        
        # Control flags
        self.is_running = False
        self.is_paused = False
        
        # Threads
        self.stream_a_thread = None
        self.stream_b_thread = None
        self.stream_b_timer = None
        self.audio_broadcaster_thread = None
        self.gap_monitor_thread = None
        
        # Lock for thread safety
        self.lock = threading.Lock()
    
    def start(self):
        """Start dual stream processing with Primary/Backup model."""
        self.is_running = True
        self.last_stream_a_output = datetime.now()
        
        print("\n" + "=" * 60)
        print("   DUAL STREAM MANAGER - PRIMARY/BACKUP MODEL")
        print("=" * 60)
        print(f"   Stream A: PRIMARY (outputs to display)")
        print(f"   Stream B: BACKUP (starts in {self.stream_b_delay}s, buffers content)")
        print(f"   Gap threshold: {self.gap_threshold}s (triggers backup release)")
        print(f"   Buffer duration: {self.buffer_duration}s")
        print("=" * 60)
        
        # Start audio broadcaster
        self.audio_broadcaster_thread = threading.Thread(target=self._broadcast_audio, daemon=True)
        self.audio_broadcaster_thread.start()
        
        # Start Stream A immediately as PRIMARY
        self.stream_a_thread = threading.Thread(target=self._run_stream_a, daemon=True)
        self.stream_a_thread.start()
        self.stream_a_active = True
        
        # Start gap monitor
        self.gap_monitor_thread = threading.Thread(target=self._monitor_gaps, daemon=True)
        self.gap_monitor_thread.start()
        
        # Schedule Stream B to start after delay
        self.stream_b_timer = threading.Timer(self.stream_b_delay, self._start_stream_b)
        self.stream_b_timer.start()
    
    def _broadcast_audio(self):
        """Broadcast audio to both stream queues."""
        chunks_broadcast = 0
        
        for chunk, timestamp in self.audio_streamer.audio_generator():
            if not self.is_running:
                break
            
            if hasattr(self.audio_streamer, 'is_finished'):
                if self.audio_streamer.is_finished and self.audio_streamer.audio_queue.empty():
                    break
            
            # Send to both streams
            self.stream_a_queue.put((chunk, timestamp))
            if self.stream_b_started:
                self.stream_b_queue.put((chunk, timestamp))
            
            chunks_broadcast += 1
            if chunks_broadcast % 500 == 0:
                print(f"   [BROADCAST] {chunks_broadcast} chunks")
        
        # Signal end
        self.stream_a_queue.put((None, None))
        self.stream_b_queue.put((None, None))
        print(f"   [BROADCAST] Complete - {chunks_broadcast} chunks")
    
    def _start_stream_b(self):
        """Start Stream B as BACKUP."""
        if not self.is_running:
            return
        
        print(f"\n   [BACKUP] Stream B starting as BACKUP (buffering mode)")
        self.stream_b_started = True
        self.stream_b_thread = threading.Thread(target=self._run_stream_b, daemon=True)
        self.stream_b_thread.start()
        self.stream_b_active = True
    
    def _run_stream_a(self):
        """Run Stream A as PRIMARY - outputs directly to display."""
        restart_count = 0
        
        while self.is_running:
            try:
                if self.is_paused:
                    time.sleep(0.5)
                    continue
                
                # Mark as not restarting
                self.stream_a_restarting = False
                
                def request_generator():
                    while self.is_running and not self.is_paused:
                        try:
                            chunk, timestamp = self.stream_a_queue.get(timeout=1)
                            if chunk is None:
                                break
                            yield speech.StreamingRecognizeRequest(audio_content=chunk)
                        except queue.Empty:
                            if hasattr(self.audio_streamer, 'is_finished') and self.audio_streamer.is_finished:
                                break
                            continue
                
                responses = self.speech_client.streaming_recognize(
                    self.streaming_config, request_generator()
                )
                
                for response in responses:
                    if not self.is_running:
                        break
                    
                    for result in response.results:
                        if result.is_final:
                            transcript = result.alternatives[0].transcript
                            
                            if not transcript or not transcript.strip():
                                continue
                            
                            # PRIMARY outputs directly
                            self.results_queue.put({
                                'transcript': transcript,
                                'stream_id': 'A',
                                'timestamp': datetime.now(),
                                'is_final': True,
                                'source': 'primary'
                            })
                            
                            # Update last output time
                            self.last_stream_a_output = datetime.now()
                            
                            with self.lock:
                                self.stream_a_segments += 1
                            
                            print(f"   [PRIMARY] Stream A: {len(transcript.split())} words")
                
            except Exception as e:
                error_msg = str(e)
                
                if "deadline exceeded" in error_msg.lower() or "timeout" in error_msg.lower():
                    restart_count += 1
                    with self.lock:
                        self.stream_a_restarts += 1
                    
                    # Mark as restarting - this triggers backup release
                    self.stream_a_restarting = True
                    
                    print(f"\n   [PRIMARY] Stream A: RESTARTING #{restart_count} - Backup will fill gap")
                    
                    time.sleep(0.5)
                    continue
                else:
                    print(f"\n   [PRIMARY] Stream A: Error - {error_msg}")
                    self.stream_a_restarting = True
                    time.sleep(1)
                    continue
            
            if hasattr(self.audio_streamer, 'is_finished') and self.audio_streamer.is_finished:
                print(f"\n   [PRIMARY] Stream A: Audio finished")
                break
        
        with self.lock:
            self.stream_a_active = False
    
    def _run_stream_b(self):
        """Run Stream B as BACKUP - buffers content, releases during gaps."""
        restart_count = 0
        
        while self.is_running:
            try:
                if self.is_paused:
                    time.sleep(0.5)
                    continue
                
                def request_generator():
                    while self.is_running and not self.is_paused:
                        try:
                            chunk, timestamp = self.stream_b_queue.get(timeout=1)
                            if chunk is None:
                                break
                            yield speech.StreamingRecognizeRequest(audio_content=chunk)
                        except queue.Empty:
                            if hasattr(self.audio_streamer, 'is_finished') and self.audio_streamer.is_finished:
                                break
                            continue
                
                responses = self.speech_client.streaming_recognize(
                    self.streaming_config, request_generator()
                )
                
                for response in responses:
                    if not self.is_running:
                        break
                    
                    for result in response.results:
                        if result.is_final:
                            transcript = result.alternatives[0].transcript
                            
                            if not transcript or not transcript.strip():
                                continue
                            
                            # BACKUP: Add to buffer instead of outputting
                            with self.buffer_lock:
                                self.stream_b_buffer.append((datetime.now(), transcript))
                                self.stream_b_segments_buffered += 1
                                
                                # Keep buffer size limited
                                cutoff = datetime.now() - timedelta(seconds=self.buffer_duration)
                                self.stream_b_buffer = [
                                    (ts, txt) for ts, txt in self.stream_b_buffer
                                    if ts > cutoff
                                ]
                            
                            print(f"   [BACKUP] Stream B: Buffered {len(transcript.split())} words (buffer: {len(self.stream_b_buffer)} items)")
                
            except Exception as e:
                error_msg = str(e)
                
                if "deadline exceeded" in error_msg.lower() or "timeout" in error_msg.lower():
                    restart_count += 1
                    with self.lock:
                        self.stream_b_restarts += 1
                    
                    print(f"\n   [BACKUP] Stream B: Restart #{restart_count}")
                    time.sleep(0.5)
                    continue
                else:
                    print(f"\n   [BACKUP] Stream B: Error - {error_msg}")
                    time.sleep(1)
                    continue
            
            if hasattr(self.audio_streamer, 'is_finished') and self.audio_streamer.is_finished:
                print(f"\n   [BACKUP] Stream B: Audio finished")
                break
        
        with self.lock:
            self.stream_b_active = False
    
    def _monitor_gaps(self):
        """Monitor for gaps in Stream A output and release backup buffer.
        
        IMPORTANT: Only releases buffer when Stream A is ACTUALLY restarting,
        not just during normal pauses between utterances.
        """
        while self.is_running:
            time.sleep(0.5)  # Check every 500ms
            
            if not self.stream_b_started:
                continue
            
            # ONLY release buffer when Stream A is explicitly restarting
            # Normal pauses (even long ones) should NOT trigger release
            if self.stream_a_restarting:
                time_since_output = (datetime.now() - self.last_stream_a_output).total_seconds()
                
                # Only release if we've been restarting for more than gap_threshold
                # This prevents releasing during brief restart moments
                if time_since_output > self.gap_threshold:
                    with self.buffer_lock:
                        if self.stream_b_buffer:
                            # Release all buffered content
                            items_to_release = list(self.stream_b_buffer)
                            self.stream_b_buffer = []  # Clear buffer
                            
                            if items_to_release:
                                self.gaps_filled += 1
                                print(f"\n   [GAP FILL] Stream A restarting - Releasing {len(items_to_release)} buffered items from Stream B")
                                
                                for ts, transcript in items_to_release:
                                    self.results_queue.put({
                                        'transcript': transcript,
                                        'stream_id': 'B',
                                        'timestamp': ts,
                                        'is_final': True,
                                        'source': 'backup_fill'
                                    })
                                    
                                    with self.lock:
                                        self.stream_b_segments += 1
                                        self.stream_b_segments_released += 1
    
    def get_next_result(self, timeout: float = 1.0):
        """Get next result from display queue."""
        try:
            return self.results_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def stop(self):
        """Stop all streams."""
        self.is_running = False
        
        if self.stream_b_timer:
            self.stream_b_timer.cancel()
        
        # Wait for threads
        for thread in [self.audio_broadcaster_thread, self.stream_a_thread, 
                       self.stream_b_thread, self.gap_monitor_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=2)
    
    def get_statistics(self) -> dict:
        """Get dual stream statistics."""
        with self.lock:
            return {
                'stream_a_segments': self.stream_a_segments,
                'stream_b_segments': self.stream_b_segments,
                'stream_b_buffered': self.stream_b_segments_buffered,
                'stream_b_released': self.stream_b_segments_released,
                'total_segments': self.stream_a_segments + self.stream_b_segments,
                'gaps_filled': self.gaps_filled,
                'stream_a_restarts': self.stream_a_restarts,
                'stream_b_restarts': self.stream_b_restarts,
                'stream_a_active': self.stream_a_active,
                'stream_b_active': self.stream_b_active,
                'buffer_size': len(self.stream_b_buffer),
            }


# =============================================================================
# HYBRID BUFFER - For Enhanced Context Quality (Mode 17)
# =============================================================================

class HybridBuffer:
    """
    Buffers speech recognition fragments until complete sentences are formed.
    
    Triggers translation when ANY of these conditions is met:
    1. Sentence ending detected (. ? !)
    2. Word count reaches threshold (default: 50 words)
    3. Time elapsed reaches timeout (default: 15 seconds)
    
    This improves translation quality by providing more complete context
    at the cost of increased latency.
    """
    
    def __init__(self, max_words: int = 50, timeout_seconds: float = 15.0,
                 detect_sentence_endings: bool = True):
        """
        Initialize hybrid buffer.
        
        Args:
            max_words: Maximum words before forcing translation
            timeout_seconds: Maximum time before forcing translation
            detect_sentence_endings: Whether to trigger on . ? !
        """
        self.max_words = max_words
        self.timeout_seconds = timeout_seconds
        self.detect_sentence_endings = detect_sentence_endings
        
        # Buffer state
        self.buffer = []  # List of transcript fragments
        self.buffer_start_time = None
        self.total_words = 0
        
        # Statistics
        self.flushes_by_sentence = 0
        self.flushes_by_words = 0
        self.flushes_by_timeout = 0
        self.flushes_by_restart = 0  # Track restart flushes (Option C)
        self.flushes_by_final = 0    # Track final/stop flushes
        self.total_flushes = 0
        
        # Lock for thread safety
        self.lock = threading.Lock()
    
    def add_fragment(self, transcript: str, is_final: bool = False) -> tuple:
        """
        Add a transcript fragment to the buffer.
        
        Args:
            transcript: The transcript text from speech recognition
            is_final: Whether this is a FINAL result from Google
            
        Returns:
            tuple: (should_flush, buffered_text, flush_reason)
            - should_flush: True if buffer should be translated now
            - buffered_text: The complete buffered text to translate
            - flush_reason: 'sentence', 'words', 'timeout', 'final', or None
        """
        with self.lock:
            # Start timer on first fragment
            if self.buffer_start_time is None:
                self.buffer_start_time = datetime.now()
            
            # Add fragment to buffer
            if transcript and transcript.strip():
                self.buffer.append(transcript.strip())
                self.total_words = len(' '.join(self.buffer).split())
            
            # Check flush conditions
            buffered_text = ' '.join(self.buffer)
            flush_reason = None
            
            # Condition 1: Sentence ending detected
            if self.detect_sentence_endings and buffered_text:
                # Check if text ends with sentence-ending punctuation
                stripped = buffered_text.rstrip()
                if stripped and stripped[-1] in '.?!':
                    flush_reason = 'sentence'
                    self.flushes_by_sentence += 1
            
            # Condition 2: Word count threshold reached
            if flush_reason is None and self.total_words >= self.max_words:
                flush_reason = 'words'
                self.flushes_by_words += 1
            
            # Condition 3: Timeout elapsed
            if flush_reason is None and self.buffer_start_time:
                elapsed = (datetime.now() - self.buffer_start_time).total_seconds()
                if elapsed >= self.timeout_seconds:
                    flush_reason = 'timeout'
                    self.flushes_by_timeout += 1
            
            # Condition 4: Final result with content (force flush remaining)
            if flush_reason is None and is_final and buffered_text:
                # Only flush on final if we have meaningful content
                if self.total_words >= 5:  # At least 5 words
                    flush_reason = 'final'
            
            # Should we flush?
            should_flush = flush_reason is not None
            
            if should_flush:
                self.total_flushes += 1
                # Reset buffer
                result_text = buffered_text
                self._reset_buffer()
                return (True, result_text, flush_reason)
            else:
                return (False, None, None)
    
    def _reset_buffer(self):
        """Reset buffer state (must be called with lock held)."""
        self.buffer = []
        self.buffer_start_time = None
        self.total_words = 0
    
    def flush(self, reason: str = 'manual') -> tuple:
        """
        Force flush the buffer regardless of conditions.
        
        Args:
            reason: Why the flush is happening ('restart', 'final', 'manual')
        
        Returns:
            tuple: (has_content, buffered_text)
        """
        with self.lock:
            if self.buffer:
                buffered_text = ' '.join(self.buffer)
                self._reset_buffer()
                self.total_flushes += 1
                
                # Track flush reason
                if reason == 'restart':
                    self.flushes_by_restart += 1
                elif reason == 'final':
                    self.flushes_by_final += 1
                
                return (True, buffered_text)
            return (False, None)
    
    def get_buffer_status(self) -> dict:
        """Get current buffer status."""
        with self.lock:
            elapsed = 0
            if self.buffer_start_time:
                elapsed = (datetime.now() - self.buffer_start_time).total_seconds()
            
            return {
                'words': self.total_words,
                'fragments': len(self.buffer),
                'elapsed_seconds': elapsed,
                'time_remaining': max(0, self.timeout_seconds - elapsed),
            }
    
    def get_statistics(self) -> dict:
        """Get buffer statistics."""
        with self.lock:
            return {
                'total_flushes': self.total_flushes,
                'flushes_by_sentence': self.flushes_by_sentence,
                'flushes_by_words': self.flushes_by_words,
                'flushes_by_timeout': self.flushes_by_timeout,
                'flushes_by_restart': self.flushes_by_restart,
                'flushes_by_final': self.flushes_by_final,
                'current_buffer_words': self.total_words,
            }


# =============================================================================
# TEST HARNESS MAIN SYSTEM
# =============================================================================

class TestHarnessSystem:
    """Main test harness system with full instrumentation"""
    
    SERMON_CONTEXT_HINTS = [
        # =================================================================
        # PORTUGUESE THEOLOGICAL TERMS (~480 hints)
        # Google Speech API limit: 500 phrases per SpeechContext
        # =================================================================
        
        # --- Core Theological Terms ---
        "graça", "salvação", "redenção", "Escrituras", "Evangelho",
        "pecado", "arrependimento", "fé", "esperança", "amor",
        "justificação", "santificação", "glorificação", "regeneração",
        "eleição", "predestinação", "soberania", "providência",
        "onipotência", "onisciência", "onipresença", "imutabilidade",
        "santidade", "justiça", "misericórdia", "bondade", "fidelidade",
        "verdade", "sabedoria", "eternidade",
        
        # --- Biblical Books (Portuguese) ---
        "Gênesis", "Êxodo", "Levítico", "Números", "Deuteronômio",
        "Josué", "Juízes", "Rute", "Samuel", "Reis", "Crônicas",
        "Esdras", "Neemias", "Ester", "Jó", "Salmos", "Provérbios",
        "Eclesiastes", "Cantares", "Isaías", "Jeremias", "Lamentações",
        "Ezequiel", "Daniel", "Oséias", "Joel", "Amós", "Obadias",
        "Jonas", "Miquéias", "Naum", "Habacuque", "Sofonias", "Ageu",
        "Zacarias", "Malaquias", "Mateus", "Marcos", "Lucas", "João",
        "Atos", "Romanos", "Coríntios", "Gálatas", "Efésios",
        "Filipenses", "Colossenses", "Tessalonicenses", "Timóteo",
        "Tito", "Filemom", "Hebreus", "Tiago", "Pedro", "Judas",
        "Apocalipse",
        
        # --- God, Christ, Holy Spirit ---
        "Deus", "Senhor", "Jesus", "Cristo", "Espírito Santo",
        "Trindade", "Pai", "Filho", "Messias", "Salvador",
        "Redentor", "Cordeiro de Deus", "Filho de Deus", "Filho do Homem",
        "encarnação", "ressurreição", "ascensão", "segunda vinda",
        "divindade", "humanidade de Cristo", "natureza divina",
        "nascimento virginal", "Criador", "Sustentador", "Juiz",
        "Rei", "Profeta", "Sacerdote", "Mediador", "Intercessor",
        "Advogado", "Consolador", "Paracleto", "Jeová", "Emanuel",
        "Alfa e Ômega", "Verbo", "Logos", "Palavra",
        
        # --- Church and Worship ---
        "igreja", "congregação", "irmãos", "irmãs", "comunhão",
        "adoração", "louvor", "oração", "pregação", "sermão",
        "batismo", "ceia do Senhor", "santa ceia", "ordenanças",
        "discipulado", "evangelismo", "missões", "ministério",
        "pastor", "presbítero", "diácono", "ancião", "bispo",
        "apóstolo", "profeta", "evangelista", "mestre",
        "rebanho", "ovelhas", "corpo de Cristo", "noiva de Cristo",
        "templo", "santuário", "tabernáculo", "culto",
        "oferta", "dízimo", "mordomia",
        
        # --- Sermon Phrases ---
        "abram suas Bíblias", "vamos ler", "o texto diz",
        "o apóstolo Paulo", "o profeta", "nosso Senhor",
        "a Palavra de Deus", "as Escrituras dizem", "está escrito",
        "neste versículo", "neste texto", "nesta passagem",
        "o contexto", "o significado", "a aplicação",
        "vejamos", "observem", "notem", "considerem",
        "em primeiro lugar", "em segundo lugar", "finalmente",
        "o que isso significa", "vamos orar", "amém", "aleluia",
        "assim diz o Senhor", "ouçam", "prestem atenção",
        "versículo", "capítulo", "passagem", "contexto histórico",
        
        # --- Reformed Theology ---
        "depravação total", "eleição incondicional", "expiação limitada",
        "graça irresistível", "perseverança dos santos",
        "sola fide", "sola gratia", "sola scriptura",
        "solus Christus", "soli Deo gloria", "cinco solas",
        "aliança", "pacto", "promessa", "cumprimento",
        "aliança da graça", "teologia reformada", "calvinismo",
        "livre arbítrio", "servo arbítrio", "doutrinas da graça",
        
        # --- Sin and Salvation ---
        "pecado original", "queda", "Adão", "Eva", "tentação",
        "pecador", "perdão", "compaixão", "condenação", "julgamento",
        "juízo final", "inferno", "céu", "paraíso", "lago de fogo",
        "vida eterna", "morte eterna", "cruz", "sangue", "sacrifício",
        "propiciação", "expiação", "reconciliação", "resgate",
        "imputação", "substituição", "conversão", "novo nascimento",
        "nascer de novo", "confissão",
        
        # --- Christian Life ---
        "obediência", "submissão", "humildade", "serviço", "testemunho",
        "fruto do Espírito", "dons espirituais", "jejum", "meditação",
        "alegria", "paz", "paciência", "benignidade", "mansidão",
        "domínio próprio", "provação", "sofrimento", "perseguição",
        "batalha espiritual", "armadura de Deus", "espada do Espírito",
        "escudo da fé", "crescimento", "maturidade",
        
        # --- Historical References ---
        "Irineu", "Agostinho", "Calvino", "Lutero", "Zwínglio",
        "Spurgeon", "Edwards", "Reformadores", "Reforma Protestante",
        "pais da igreja", "pais apostólicos", "Nicéia", "Calcedônia",
        "credo", "confissão", "catecismo", "Westminster",
        "heresia", "ortodoxia", "apostasia", "gnosticismo",
        "arianismo", "pelagianismo", "cristologia", "soteriologia",
        "escatologia", "pneumatologia", "eclesiologia",
        "exegese", "hermenêutica", "homilética", "apologética",
        
        # --- Gnosticism & Early Church Terms (NEW) ---
        "protognosticismo", "proto-gnosticismo", "proto gnosticismo",
        "gnóstico", "gnósticos", "gnosis", "epignosis", "epignose",
        "pneumático", "pneumáticos", "pneuma",
        "cosmogonia", "cosmogonias", "cosmologia",
        "embrionário", "embrionária",
        "carpocratiano", "carpocratianos", "Carpócrates",
        "valentiniano", "valentinianos", "Valentim",
        "Irineu de Leão", "Irineu de Lyon", "bispo de Leão",
        "Adversus Haereses", "Contra Heresias", "contra as heresias",
        "Aion", "Aeons", "éon", "éons", "emanação", "emanações",
        "demiurgo", "pleroma", "kenoma",
        "docetismo", "doceta", "docetas",
        "hílico", "hílicos", "psíquico", "psíquicos",
        
        # --- Portuguese Idioms & Expressions (NEW) ---
        "alfinetada", "alfinetadas", "alfinete", "alfinetes", "alfinetar",
        "dar risada", "dá vontade", "coisa de hospício", "conversa de louco",
        "gororoba", "feijoada", "galinhada", "mistureba",
        "se debruçar", "se debruçou", "debruçar sobre",
        "apulular", "pululou", "pululando",
        "ensejo", "deu ensejo",
        
        # --- Latin Theological Terms (NEW) ---
        "Adversus", "Haereses", "Eresiae",
        "corpus", "corporalmente", "habita corporalmente",
        "plenitude", "plenitudo", "divindade",
        "sola", "solus", "soli",
        
        # --- Numbers and References (NEW) ---
        "século primeiro", "século segundo", "século II", "século I",
        "ano 62", "160 quilômetros", "100 anos depois",
        "versículo 9", "versículo 10", "versículo 14",
        "Colossenses 2", "2 Coríntios", "primeiro Coríntios",
        
        # --- Bible Locations ---
        "Jerusalém", "Israel", "Judeia", "Galileia", "Samaria",
        "Roma", "Éfeso", "Corinto", "Colossos", "Filipos",
        "Tessalônica", "Antioquia", "Damasco", "Atenas",
        "Ásia Menor", "Egito", "Babilônia", "Pérsia", "Grécia",
        "Jordão", "Monte Sinai", "Monte das Oliveiras", "Gólgota",
        "Calvário", "Getsêmani", "Terra Prometida", "Canaã",
        "Vale do Rio Lico", "Hierápolis", "Laodiceia",
        
        # --- Bible People ---
        "Abraão", "Isaque", "Jacó", "José", "Moisés", "Arão",
        "Josué", "Calebe", "Gideão", "Sansão", "Samuel", "Davi",
        "Salomão", "Elias", "Eliseu", "Isaías", "Jeremias",
        "Ezequiel", "Daniel", "Jonas", "Paulo", "Pedro", "João",
        "Tiago", "André", "Filipe", "Mateus", "Tomé",
        "Barnabé", "Silas", "Timóteo", "Tito", "Apolo",
        "Priscila", "Áquila", "Lucas", "Marcos", "Estêvão",
        "Nicodemos", "Zaqueu", "Lázaro", "Marta", "Maria Madalena",
        "Herodes", "Pilatos", "fariseus", "saduceus", "escribas",
        
        # --- Common Connector Words (trimmed to stay under 500) ---
        "portanto", "porque", "pois", "entretanto", "todavia",
        "consequentemente", "além disso", "de fato", "na verdade",
        
        # --- Preaching Style Words (trimmed) ---
        "amados", "queridos", "povo de Deus", "santos",
        "vejam", "percebam", "entendam", "lembrem-se",
        
        # --- English terms (for bilingual recognition) ---
        "expository sermon", "verse by verse", "Biblical exposition",
        "Reformed theology", "grace", "salvation", "redemption",
    ]
    
    # =================================================================
    # POST-RECOGNITION CORRECTIONS
    # =================================================================
    # Fixes common misrecognitions from Google Speech API
    # Applied AFTER speech recognition, BEFORE translation
    # Format: "misrecognized text": "correct text"
    # Uses case-insensitive matching
    # =================================================================
    
    POST_RECOGNITION_CORRECTIONS = {
        # Gnosticism-related corrections
        "próprio velocíssimo": "proto-gnosticismo",
        "próprio sismo": "proto-gnosticismo",
        "próprio gnosticismo": "proto-gnosticismo",
        "proto velocíssimo": "proto-gnosticismo",
        "protognostico": "proto-gnóstico",
        
        # Carpocratians
        "karpa crate ano": "carpocratiano",
        "karpa crate": "carpocratiano",
        "carpa crate ano": "carpocratiano",
        "carpa crateano": "carpocratiano",
        "carpa cratiano": "carpocratiano",
        "era um país era um resto": "era um patife era um perverso",  # NEW
        "um resto da pior": "um perverso da pior",  # NEW
        
        # Latin book title
        "diversos heresias": "Adversus Haereses",
        "diversas heresias": "Adversus Haereses",
        "adverso heresias": "Adversus Haereses",
        
        # Portuguese idioms
        "calcinha": "alfinetada",  # Only in sermon context
        "dava cada calcinha": "dava cada alfinetada",
        "cada calcinha": "cada alfinetada",
        
        # City name
        "coloque-se cavalinho": "Colossus ficava ali",
        "coloque se cavalinho": "Colossus ficava ali",
        "colosso cavalinho": "Colossus ficava ali",
        
        # Theological terms
        "próprio gnostica": "proto-gnóstica",
        "próprio gnóstico": "proto-gnóstico",
        "diagnóstico": "gnóstico",  # Common misrecognition
        "diagnóstica": "gnóstica",
        
        # Irenaeus
        "Irineu de leão": "Irineu de Leão",
        "irineu de león": "Irineu de Leão",
        
        # Gaul/France
        "Gávea": "Gália",
        "a Gávea": "a Gália",
        
        # Book references
        "né testamentários": "neotestamentários",
        "neo testamentários": "neotestamentários",
        "né o testamentários": "neotestamentários",  # NEW
        
        # Common sermon misrecognitions
        "centro cristão": "centro cristão",  # Keep as is
        "Santo Cristão": "centro cristão",
        
        # Aion/Angel
        "haeum": "Aion",
        "a eum": "Aion",
        "aeon": "Aion",
        
        # Vale do Rio Lico
        "Rio Nico": "Rio Lico",
        "rio Nico": "Rio Lico",
        
        # Other common errors
        "feitas": "seitas",  # "diversas feitas" -> "diversas seitas"
        "é o filé": "alfineta",
        "ele é o filé": "ele alfineta",
        
        # NEW corrections from full sermon analysis
        "e neta": "inepta",  # Word split error
        "passou no novo": "passou o ano novo",  # Missing word
        "luz orientar": "nos orientar",  # Misheard
        "foto saiu retrato": "foto está aí o retrato",  # Misheard
        "concede meu": "estou com sede meu",  # Misheard phrase
        "devia mergulhado": "vivia mergulhado",  # Verb error
        "que o universo": "que universo",  # Extra article
        "ensinam são esses": "ensinos são esses",  # Verb/noun confusion
        "Motorola": "Motorola",  # Keep brand name
        "iPhone": "iPhone",  # Keep brand name
        "Itaú": "Itaú",  # Keep brand name
    }
    
    @classmethod
    def apply_post_recognition_corrections(cls, text: str) -> str:
        """
        Apply post-recognition corrections to fix common misrecognitions.
        
        Args:
            text: Raw transcript from Google Speech API
            
        Returns:
            Corrected transcript
        """
        if not text:
            return text
            
        corrected = text
        corrections_made = []
        
        for wrong, correct in cls.POST_RECOGNITION_CORRECTIONS.items():
            # Case-insensitive search
            import re
            pattern = re.compile(re.escape(wrong), re.IGNORECASE)
            if pattern.search(corrected):
                corrected = pattern.sub(correct, corrected)
                corrections_made.append(f"'{wrong}' → '{correct}'")
        
        if corrections_made:
            print(f"   [CORRECTIONS] {', '.join(corrections_made)}")
        
        return corrected
    
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
        self.is_hard_paused = False  # Hard pause = full stop, no API calls
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
        self.display.root.bind('<Control-Shift-P>', self._pause)       # Soft pause
        self.display.root.bind('<Control-Shift-p>', self._pause)
        self.display.root.bind('<Control-Shift-X>', self._hard_pause)  # Hard pause (full stop)
        self.display.root.bind('<Control-Shift-x>', self._hard_pause)
        self.display.root.bind('<Control-Shift-R>', self._resume)      # Resume from either
        self.display.root.bind('<Control-Shift-r>', self._resume)
        self.display.root.bind('<Control-Shift-S>', self._stop)        # Stop test
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
        
        # Stream tracking
        self.stream_start_time = None
        self.first_result_time = None
        self.stream_restart_count = 0
        
        # Early interim display tracking
        self.interim_words_displayed = 0  # How many words from current interim we've displayed
        self.interim_text_displayed = ""  # What text we've already shown from interim
        
        # Restart gap tracking
        self.restart_gaps = []  # List of (restart_time, gap_duration, last_segment_time)
        self.last_segment_time = None  # When we last received a segment
        
        # Skipped content tracking
        self.skipped_finals_count = 0  # FINAL results skipped due to too few new words
        self.skipped_finals_words = 0  # Total words in skipped FINAL results
        
        # Dual stream manager reference (Mode 16)
        self.dual_stream_manager = None
        
        # Hybrid buffer (Mode 17)
        self.hybrid_buffer = None
        self.last_interim_for_restart = None  # Track last interim for restart recovery
        self.last_interim_word_count = 0
        if self.test_config.get('hybrid_buffer_enabled', False):
            self.hybrid_buffer = HybridBuffer(
                max_words=self.test_config.get('buffer_max_words', 50),
                timeout_seconds=self.test_config.get('buffer_timeout_seconds', 15.0),
                detect_sentence_endings=self.test_config.get('buffer_sentence_endings', True)
            )
            print(f"   Hybrid Buffer: ENABLED (max {self.test_config.get('buffer_max_words', 50)} words, "
                  f"{self.test_config.get('buffer_timeout_seconds', 15.0)}s timeout)")
        
        # Translation logging and context tracking (NEW)
        self.translation_log = []  # List of (timestamp, source_text, translations_dict) tuples
        self.previous_chunks = deque(maxlen=3)  # Store last N chunks for context
        self.translation_log_file = None  # File handle for translation log
        
        # Mode 13: Glossary corrections tracking
        self.glossary_corrections_log = []  # List of corrections made
        
        # Mode 13: Async context comparison
        self.async_context_differences = []  # Differences found by async comparison
        self.async_comparison_queue = queue.Queue()  # Queue for async worker
        self.async_worker_running = False
        self.async_worker_thread = None
        
        # Start async context worker if enabled
        if self.test_config.get('async_context_comparison', False):
            self.async_worker_running = True
            self.async_worker_thread = threading.Thread(target=self._async_context_worker, daemon=True)
            self.async_worker_thread.start()
            print(f"   Async Context Comparison: ENABLED (background thread)")
        
        if self.test_config.get('use_glossary', False):
            print(f"   Glossary Lookup: ENABLED ({len(THEOLOGICAL_GLOSSARY)} terms)")
        
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
        """Soft Pause - stops display but queue continues building"""
        if not self.is_paused:
            self.is_paused = True
            self.is_hard_paused = False  # Soft pause
            self.pause_start_time = datetime.now()
            self.display.set_paused(True, hard=False)
            
            if self.active_start_time:
                self.total_active_time += (datetime.now() - self.active_start_time).total_seconds()
            
            print(f"\n⏸️  [{datetime.now().strftime('%H:%M:%S')}] SOFT PAUSED (queue still building)")
            print(f"    Press Ctrl+Shift+R to resume, or Ctrl+Shift+X for hard stop")
    
    def _hard_pause(self, event=None):
        """Hard Pause - full stop, no API calls, clears queues"""
        if not self.is_paused or not self.is_hard_paused:
            was_soft_paused = self.is_paused and not getattr(self, 'is_hard_paused', False)
            
            self.is_paused = True
            self.is_hard_paused = True
            self.pause_start_time = datetime.now() if not was_soft_paused else self.pause_start_time
            self.display.set_paused(True, hard=True)
            
            if self.active_start_time and not was_soft_paused:
                self.total_active_time += (datetime.now() - self.active_start_time).total_seconds()
            
            # Clear queues to stop all data flow
            queues_cleared = self._clear_all_queues()
            
            print(f"\n⏹️  [{datetime.now().strftime('%H:%M:%S')}] HARD STOPPED")
            print(f"    Audio streaming: STOPPED")
            print(f"    Translation API: STOPPED")
            print(f"    Display queue: CLEARED ({queues_cleared['display']} items)")
            print(f"    Audio buffer: CLEARED ({queues_cleared['audio']} chunks)")
            print(f"    Press Ctrl+Shift+R to resume fresh")
    
    def _clear_all_queues(self):
        """Clear all queues and buffers for hard pause"""
        cleared = {'display': 0, 'audio': 0, 'translation': 0}
        
        # Clear display queue (text_queue in TestHarnessDisplay)
        if hasattr(self.display, 'text_queue'):
            while not self.display.text_queue.empty():
                try:
                    self.display.text_queue.get_nowait()
                    cleared['display'] += 1
                except queue.Empty:
                    break
        
        # Clear audio streamer buffer
        if hasattr(self, 'audio_streamer') and self.audio_streamer:
            if hasattr(self.audio_streamer, 'audio_queue'):
                while not self.audio_streamer.audio_queue.empty():
                    try:
                        self.audio_streamer.audio_queue.get_nowait()
                        cleared['audio'] += 1
                    except queue.Empty:
                        break
        
        # Clear async comparison queue if exists
        if hasattr(self, 'async_comparison_queue'):
            while not self.async_comparison_queue.empty():
                try:
                    self.async_comparison_queue.get_nowait()
                    cleared['translation'] += 1
                except queue.Empty:
                    break
        
        # Reset interim tracking for fresh start
        self.interim_words_displayed = 0
        self.interim_text_displayed = ""
        
        return cleared
    
    def _resume(self, event=None):
        """Resume from either soft or hard pause"""
        if self.is_paused:
            was_hard_paused = getattr(self, 'is_hard_paused', False)
            
            self.is_paused = False
            self.is_hard_paused = False
            self.active_start_time = datetime.now()
            self.display.set_paused(False, hard=False)
            
            if self.pause_start_time:
                self.total_pause_time += (datetime.now() - self.pause_start_time).total_seconds()
            
            if was_hard_paused:
                print(f"\n▶️  [{datetime.now().strftime('%H:%M:%S')}] RESUMED (fresh start)")
            else:
                print(f"\n▶️  [{datetime.now().strftime('%H:%M:%S')}] RESUMED")
    
    def _stop(self, event=None):
        print("\n🛑 Stopping test...")
        self.display.stop()
    
    def translate_to_multiple(self, text, use_context=True):
        """Translate text to all target languages
        
        Args:
            text: Text to translate
            use_context: Whether to include previous chunks as context hint
        """
        translations = {}
        source_base = self.source_language[0].split('-')[0]
        
        # Build context hint if enabled (for synchronous context - Mode 12 style, usually disabled)
        context_enabled = self.test_config.get('context_aware_translation', False) and use_context
        context_hint = ""
        if context_enabled and self.previous_chunks:
            num_chunks = self.test_config.get('context_chunks', 1)
            context_parts = list(self.previous_chunks)[-num_chunks:]
            if context_parts:
                context_hint = " ".join(context_parts)
        
        for lang_code, lang_name in self.target_languages:
            target_base = lang_code.split('-')[0] if '-' in lang_code else lang_code
            try:
                # If context is available, prepend it with a separator
                # Google Translate will use it for better context but we extract only the new part
                if context_hint:
                    # Use bracket separator if enabled (more reliable than |||)
                    use_brackets = self.test_config.get('use_bracket_separator', False)
                    
                    if use_brackets:
                        # Bracket format: [[[CONTEXT]]] NEW_TEXT
                        # This is less likely to be mangled by translation
                        full_text = f"[[[{context_hint}]]] {text}"
                        result = self.translate_client.translate(
                            full_text, target_language=target_base,
                            source_language=source_base, format_='text', model='nmt'
                        )
                        translated_full = result['translatedText']
                        
                        # Try to extract text after ]]]
                        if ']]]' in translated_full:
                            translations[lang_name] = translated_full.split(']]]')[-1].strip()
                        elif ']]' in translated_full:
                            # Fallback if one bracket was removed
                            translations[lang_name] = translated_full.split(']]')[-1].strip()
                        elif ']' in translated_full:
                            # Last resort - find last ]
                            parts = translated_full.rsplit(']', 1)
                            if len(parts) > 1:
                                translations[lang_name] = parts[-1].strip()
                            else:
                                # Complete failure - translate without context
                                result = self.translate_client.translate(
                                    text, target_language=target_base,
                                    source_language=source_base, format_='text', model='nmt'
                                )
                                translations[lang_name] = result['translatedText']
                        else:
                            # Brackets completely removed - translate without context
                            result = self.translate_client.translate(
                                text, target_language=target_base,
                                source_language=source_base, format_='text', model='nmt'
                            )
                            translations[lang_name] = result['translatedText']
                    else:
                        # Original ||| separator approach
                        full_text = f"{context_hint} ||| {text}"
                        result = self.translate_client.translate(
                            full_text, target_language=target_base,
                            source_language=source_base, format_='text', model='nmt'
                        )
                        # Extract only the part after the separator
                        translated_full = result['translatedText']
                        if '|||' in translated_full:
                            translations[lang_name] = translated_full.split('|||')[-1].strip()
                        elif '| |' in translated_full:
                            # Sometimes spaces get added
                            translations[lang_name] = translated_full.split('| |')[-1].strip()
                        else:
                            # Fallback - separator was translated or removed
                            # Re-translate without context to avoid showing duplicates
                            result = self.translate_client.translate(
                                text, target_language=target_base,
                                source_language=source_base, format_='text', model='nmt'
                            )
                            translations[lang_name] = result['translatedText']
                else:
                    result = self.translate_client.translate(
                        text, target_language=target_base,
                        source_language=source_base, format_='text', model='nmt'
                    )
                    translations[lang_name] = result['translatedText']
            except Exception as e:
                translations[lang_name] = f"[Error: {e}]"
        
        # Apply glossary corrections if enabled (Mode 13 - Option B)
        glossary_corrections = {}
        if self.test_config.get('use_glossary', False):
            translations, glossary_corrections = self._apply_glossary(text, translations)
        
        # Update previous chunks for next translation
        self.previous_chunks.append(text)
        
        # Log translation if enabled
        if self.test_config.get('save_translation_log', False):
            self.translation_log.append({
                'timestamp': datetime.now().isoformat(),
                'source_text': text,
                'translations': translations.copy(),
                'context_used': context_hint if context_enabled else None,
                'glossary_corrections': glossary_corrections if glossary_corrections else None
            })
        
        # Queue async context comparison if enabled (Mode 13 - Option A)
        if self.test_config.get('async_context_comparison', False):
            self._queue_async_context_comparison(text, translations.copy())
        
        # Track glossary corrections
        if glossary_corrections and self.test_config.get('generate_glossary_report', False):
            self.glossary_corrections_log.append({
                'timestamp': datetime.now().isoformat(),
                'source_text': text,
                'corrections': glossary_corrections
            })
        
        return translations
    
    def _apply_glossary(self, source_text: str, translations: Dict[str, str]) -> tuple:
        """Apply glossary corrections to translations
        
        Args:
            source_text: Original Portuguese text
            translations: Dict of translations by language name
            
        Returns:
            Tuple of (corrected_translations, corrections_made)
        """
        corrections = {}
        corrected_translations = translations.copy()
        
        case_sensitive = self.test_config.get('glossary_case_sensitive', False)
        source_lower = source_text.lower() if not case_sensitive else source_text
        
        # Check each glossary term
        for pt_term, en_term in THEOLOGICAL_GLOSSARY.items():
            pt_check = pt_term if case_sensitive else pt_term.lower()
            
            # If Portuguese term is in source text
            if pt_check in source_lower:
                # Check each translation
                for lang_name, translation in corrected_translations.items():
                    if lang_name == "English (US)" or lang_name == "English (UK)":
                        trans_lower = translation.lower() if not case_sensitive else translation
                        
                        # Check if the expected English term is present
                        en_check = en_term.lower() if not case_sensitive else en_term
                        
                        # Look for variant translations that should be corrected
                        if en_term in GLOSSARY_ENGLISH_VARIANTS:
                            variants = GLOSSARY_ENGLISH_VARIANTS[en_term]
                            for variant in variants:
                                if variant != en_term:
                                    variant_check = variant.lower() if not case_sensitive else variant
                                    if variant_check in trans_lower and en_check not in trans_lower:
                                        # Replace variant with preferred term
                                        import re
                                        pattern = re.compile(re.escape(variant), re.IGNORECASE)
                                        new_translation = pattern.sub(en_term, corrected_translations[lang_name])
                                        
                                        if new_translation != corrected_translations[lang_name]:
                                            if lang_name not in corrections:
                                                corrections[lang_name] = []
                                            corrections[lang_name].append({
                                                'portuguese': pt_term,
                                                'original': variant,
                                                'corrected': en_term
                                            })
                                            corrected_translations[lang_name] = new_translation
        
        return corrected_translations, corrections
    
    def _queue_async_context_comparison(self, source_text: str, fast_translations: Dict[str, str]):
        """Queue a segment for async context comparison
        
        Args:
            source_text: Original Portuguese text
            fast_translations: The fast (no context) translations already displayed
        """
        if not hasattr(self, 'async_comparison_queue'):
            return
        
        # Get context from previous chunks
        if self.previous_chunks:
            num_chunks = self.test_config.get('context_chunks', 1)
            context_parts = list(self.previous_chunks)[-num_chunks-1:-1]  # Exclude current chunk
            context = " ".join(context_parts) if context_parts else ""
        else:
            context = ""
        
        # Add to queue for background processing
        self.async_comparison_queue.put({
            'timestamp': datetime.now().isoformat(),
            'source_text': source_text,
            'context': context,
            'fast_translations': fast_translations,
            'segment_id': self.segment_counter
        })
    
    def _async_context_worker(self):
        """Background worker for async context comparison"""
        source_base = self.source_language[0].split('-')[0]
        
        while self.async_worker_running:
            try:
                item = self.async_comparison_queue.get(timeout=0.5)
                
                source_text = item['source_text']
                context = item['context']
                fast_translations = item['fast_translations']
                
                # Translate with context
                context_translations = {}
                
                for lang_code, lang_name in self.target_languages:
                    target_base = lang_code.split('-')[0] if '-' in lang_code else lang_code
                    try:
                        if context:
                            # Translate with context
                            full_text = f"{context} {source_text}"
                            result = self.translate_client.translate(
                                full_text, target_language=target_base,
                                source_language=source_base, format_='text', model='nmt'
                            )
                            # We want the full translation to compare flow
                            context_translations[lang_name] = result['translatedText']
                        else:
                            # No context available, skip comparison
                            context_translations[lang_name] = fast_translations.get(lang_name, "")
                    except Exception as e:
                        context_translations[lang_name] = f"[Error: {e}]"
                
                # Compare and log differences
                differences = self._compare_translations(
                    source_text, fast_translations, context_translations, context
                )
                
                if differences:
                    self.async_context_differences.append({
                        'timestamp': item['timestamp'],
                        'segment_id': item['segment_id'],
                        'source_text': source_text,
                        'context': context[:100] + "..." if len(context) > 100 else context,
                        'differences': differences
                    })
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"Async context worker error: {e}")
    
    def _compare_translations(self, source_text: str, fast: Dict[str, str], 
                             context: Dict[str, str], context_used: str) -> Dict:
        """Compare fast vs context translations and identify differences
        
        Args:
            source_text: Original Portuguese text
            fast: Fast translation (no context)
            context: Context-aware translation
            context_used: The context that was used
            
        Returns:
            Dict of differences by language, or empty dict if similar
        """
        differences = {}
        min_threshold = self.test_config.get('min_difference_threshold', 0.15)
        flag_pronouns = self.test_config.get('flag_pronoun_differences', True)
        
        # Pronouns to check (English)
        pronouns = ['he', 'she', 'it', 'him', 'her', 'his', 'they', 'them', 'their']
        
        for lang_name in fast.keys():
            fast_text = fast.get(lang_name, "")
            # For context translation, extract just the part that corresponds to source_text
            context_text = context.get(lang_name, "")
            
            # Simple word-based comparison
            fast_words = set(fast_text.lower().split())
            context_words = set(context_text.lower().split())
            
            # Calculate difference
            all_words = fast_words | context_words
            common_words = fast_words & context_words
            
            if len(all_words) > 0:
                difference_ratio = 1 - (len(common_words) / len(all_words))
            else:
                difference_ratio = 0
            
            # Check for pronoun differences
            pronoun_diff = False
            pronoun_details = []
            if flag_pronouns:
                for pronoun in pronouns:
                    in_fast = pronoun in fast_text.lower().split()
                    in_context = pronoun in context_text.lower().split()
                    if in_fast != in_context:
                        pronoun_diff = True
                        if in_fast:
                            pronoun_details.append(f"'{pronoun}' in fast only")
                        else:
                            pronoun_details.append(f"'{pronoun}' in context only")
            
            # Flag if significant difference or pronoun change
            if difference_ratio >= min_threshold or pronoun_diff:
                differences[lang_name] = {
                    'fast_translation': fast_text,
                    'context_translation': context_text[-len(fast_text)-50:] if len(context_text) > len(fast_text) else context_text,
                    'difference_ratio': difference_ratio,
                    'pronoun_difference': pronoun_diff,
                    'pronoun_details': pronoun_details,
                    'severity': 'HIGH' if pronoun_diff else ('MEDIUM' if difference_ratio >= 0.3 else 'LOW')
                }
        
        return differences
    
    def _save_translation_log(self, base_filename: str):
        """Save translation log to file for review
        
        Args:
            base_filename: Base filename (without extension) for the log
        """
        if not self.translation_log:
            print("   No translations to log")
            return None
        
        log_filename = f"{base_filename}_translations.txt"
        
        with open(log_filename, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("TRANSLATION LOG - For Bilingual Review\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Segments: {len(self.translation_log)}\n")
            f.write(f"Source Language: {self.source_language[1]}\n")
            f.write(f"Target Languages: {', '.join([l[1] for l in self.target_languages])}\n")
            f.write(f"Context-Aware Translation: {'ENABLED' if self.test_config.get('context_aware_translation') else 'DISABLED'}\n")
            f.write("\n" + "=" * 80 + "\n\n")
            
            for i, entry in enumerate(self.translation_log, 1):
                f.write(f"--- Segment {i} [{entry['timestamp'].split('T')[1][:8]}] ---\n")
                f.write(f"SOURCE: {entry['source_text']}\n")
                for lang_name, translation in entry['translations'].items():
                    f.write(f"  → {lang_name}: {translation}\n")
                if entry.get('context_used'):
                    f.write(f"  [Context: {entry['context_used'][:50]}...]\n")
                f.write("\n")
        
        print(f"   Translation log saved: {log_filename}")
        return log_filename
    
    def _save_native_speaker_review(self, base_filename: str):
        """Save a formatted review document for native speaker evaluation
        
        Creates a clean, easy-to-read document showing Portuguese source
        and English translation side by side for quality assessment.
        
        Args:
            base_filename: Base filename (without extension) for the report
        """
        if not self.translation_log:
            print("   No translations for native speaker review")
            return None
        
        review_filename = f"{base_filename}_NATIVE_SPEAKER_REVIEW.txt"
        
        # Get mode info
        mode_name = self.test_config.get('name', 'Unknown')
        context_enabled = self.test_config.get('context_aware_translation', False)
        context_chunks = self.test_config.get('context_chunks', 0)
        
        with open(review_filename, 'w', encoding='utf-8') as f:
            f.write("=" * 90 + "\n")
            f.write("    NATIVE SPEAKER REVIEW DOCUMENT\n")
            f.write("    Portuguese → English Translation Quality Assessment\n")
            f.write("=" * 90 + "\n\n")
            
            f.write("INSTRUCTIONS FOR REVIEWER:\n")
            f.write("-" * 90 + "\n")
            f.write("Please review each segment below and evaluate:\n")
            f.write("  1. Is the English translation UNDERSTANDABLE? (Can you follow the meaning?)\n")
            f.write("  2. Is the English translation ACCURATE? (Does it convey the same message?)\n")
            f.write("  3. Are there any CONFUSING parts? (Mark with [?])\n")
            f.write("  4. Are there any ERRORS? (Mark with [X])\n")
            f.write("\n")
            f.write("At the end, please provide:\n")
            f.write("  - Overall rating: ACCEPTABLE / NOT ACCEPTABLE / NEEDS IMPROVEMENT\n")
            f.write("  - Specific feedback on recurring issues\n")
            f.write("\n")
            f.write("=" * 90 + "\n\n")
            
            f.write("TEST INFORMATION:\n")
            f.write("-" * 90 + "\n")
            f.write(f"Mode: {mode_name}\n")
            f.write(f"Context Translation: {'ENABLED (' + str(context_chunks) + ' previous segments)' if context_enabled else 'DISABLED'}\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Segments: {len(self.translation_log)}\n")
            f.write(f"Source: {self.source_language[1]}\n")
            f.write(f"Target: English\n")
            f.write("\n" + "=" * 90 + "\n")
            f.write("    TRANSLATIONS FOR REVIEW\n")
            f.write("=" * 90 + "\n\n")
            
            for i, entry in enumerate(self.translation_log, 1):
                f.write(f"┌{'─' * 88}┐\n")
                f.write(f"│ SEGMENT {i:4d}                                                                         │\n")
                f.write(f"├{'─' * 88}┤\n")
                
                # Portuguese source (wrap long lines)
                source_text = entry['source_text']
                f.write(f"│ PORTUGUÊS:                                                                           │\n")
                
                # Word wrap at ~80 chars
                words = source_text.split()
                line = "│   "
                for word in words:
                    if len(line) + len(word) + 1 > 87:
                        f.write(f"{line:<89}│\n")
                        line = "│   "
                    line += word + " "
                if line.strip() != "│":
                    f.write(f"{line:<89}│\n")
                
                f.write(f"│                                                                                        │\n")
                
                # English translation
                english_text = entry['translations'].get('English (US)', 
                              entry['translations'].get('English', 
                              list(entry['translations'].values())[0] if entry['translations'] else '[No translation]'))
                
                f.write(f"│ ENGLISH:                                                                             │\n")
                
                words = english_text.split()
                line = "│   "
                for word in words:
                    if len(line) + len(word) + 1 > 87:
                        f.write(f"{line:<89}│\n")
                        line = "│   "
                    line += word + " "
                if line.strip() != "│":
                    f.write(f"{line:<89}│\n")
                
                f.write(f"│                                                                                        │\n")
                f.write(f"│ REVIEWER NOTES: ________________________________________________________              │\n")
                f.write(f"│                                                                                        │\n")
                f.write(f"└{'─' * 88}┘\n\n")
            
            # Summary section at end
            f.write("\n" + "=" * 90 + "\n")
            f.write("    REVIEWER SUMMARY\n")
            f.write("=" * 90 + "\n\n")
            f.write("Overall Rating (circle one):   ACCEPTABLE   /   NOT ACCEPTABLE   /   NEEDS IMPROVEMENT\n\n")
            f.write("Percentage of segments that were understandable: _______ %\n\n")
            f.write("Percentage of segments that were accurate: _______ %\n\n")
            f.write("Most common issues observed:\n")
            f.write("  1. _________________________________________________________________\n")
            f.write("  2. _________________________________________________________________\n")
            f.write("  3. _________________________________________________________________\n\n")
            f.write("Comparison to previous version (if applicable):\n")
            f.write("  [ ] Much better\n")
            f.write("  [ ] Somewhat better\n")
            f.write("  [ ] About the same\n")
            f.write("  [ ] Worse\n\n")
            f.write("Additional comments:\n")
            f.write("_" * 90 + "\n")
            f.write("_" * 90 + "\n")
            f.write("_" * 90 + "\n")
            f.write("_" * 90 + "\n\n")
            f.write("Reviewer name: ________________________  Date: _______________\n")
        
        print(f"   Native speaker review document saved: {review_filename}")
        return review_filename
    
    def _run_context_comparison(self, base_filename: str):
        """Run context comparison diagnostic
        
        Compares chunk-by-chunk translation vs full-context translation
        to identify potential context loss issues.
        
        Args:
            base_filename: Base filename (without extension) for the report
        """
        if not self.translation_log or len(self.translation_log) < 5:
            print("   Not enough translations for context comparison (need at least 5)")
            return None
        
        comparison_filename = f"{base_filename}_context_comparison.txt"
        
        # Concatenate all source texts
        all_source_texts = [entry['source_text'] for entry in self.translation_log]
        full_source_text = " ".join(all_source_texts)
        
        # Limit to avoid API limits (approx 5000 characters)
        if len(full_source_text) > 5000:
            # Take a sample from middle of sermon
            start_idx = len(self.translation_log) // 3
            end_idx = start_idx + min(20, len(self.translation_log) // 3)
            sample_entries = self.translation_log[start_idx:end_idx]
            sample_source = " ".join([e['source_text'] for e in sample_entries])
            sample_note = f"(Sample: segments {start_idx+1}-{end_idx} of {len(self.translation_log)})"
        else:
            sample_entries = self.translation_log
            sample_source = full_source_text
            sample_note = "(Full sermon)"
        
        print(f"   Running context comparison {sample_note}...")
        
        # Get full-context translation (translate all at once)
        try:
            full_context_translations = {}
            source_base = self.source_language[0].split('-')[0]
            
            for lang_code, lang_name in self.target_languages:
                target_base = lang_code.split('-')[0] if '-' in lang_code else lang_code
                result = self.translate_client.translate(
                    sample_source, target_language=target_base,
                    source_language=source_base, format_='text', model='nmt'
                )
                full_context_translations[lang_name] = result['translatedText']
        except Exception as e:
            print(f"   Error in full-context translation: {e}")
            return None
        
        # Get chunk-by-chunk concatenated translation
        chunk_translations = {}
        for lang_name in [l[1] for l in self.target_languages]:
            chunk_parts = [entry['translations'].get(lang_name, '') for entry in sample_entries]
            chunk_translations[lang_name] = " ".join(chunk_parts)
        
        # Write comparison report
        with open(comparison_filename, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("CONTEXT COMPARISON DIAGNOSTIC\n")
            f.write("Chunk-by-Chunk vs Full-Context Translation\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Sample: {len(sample_entries)} segments {sample_note}\n")
            f.write(f"Source Language: {self.source_language[1]}\n\n")
            
            f.write("-" * 80 + "\n")
            f.write("SOURCE TEXT (Portuguese)\n")
            f.write("-" * 80 + "\n")
            f.write(sample_source + "\n\n")
            
            for lang_name in [l[1] for l in self.target_languages]:
                f.write("=" * 80 + "\n")
                f.write(f"COMPARISON: {lang_name}\n")
                f.write("=" * 80 + "\n\n")
                
                f.write("--- CHUNK-BY-CHUNK (what congregation sees) ---\n")
                f.write(chunk_translations.get(lang_name, 'N/A') + "\n\n")
                
                f.write("--- FULL-CONTEXT (ideal translation) ---\n")
                f.write(full_context_translations.get(lang_name, 'N/A') + "\n\n")
                
                # Simple difference analysis
                chunk_words = set(chunk_translations.get(lang_name, '').lower().split())
                full_words = set(full_context_translations.get(lang_name, '').lower().split())
                
                only_in_chunk = chunk_words - full_words
                only_in_full = full_words - chunk_words
                
                f.write("--- WORD DIFFERENCES ---\n")
                f.write(f"Words only in chunk version: {len(only_in_chunk)}\n")
                if only_in_chunk and len(only_in_chunk) <= 20:
                    f.write(f"  {', '.join(list(only_in_chunk)[:20])}\n")
                f.write(f"Words only in full-context: {len(only_in_full)}\n")
                if only_in_full and len(only_in_full) <= 20:
                    f.write(f"  {', '.join(list(only_in_full)[:20])}\n")
                
                # Calculate similarity
                total_unique = len(chunk_words | full_words)
                common = len(chunk_words & full_words)
                similarity = (common / total_unique * 100) if total_unique > 0 else 0
                f.write(f"\nWord Overlap Similarity: {similarity:.1f}%\n")
                
                if similarity >= 90:
                    f.write("Status: ✅ EXCELLENT - Minimal context loss\n")
                elif similarity >= 80:
                    f.write("Status: ✅ GOOD - Minor differences, likely acceptable\n")
                elif similarity >= 70:
                    f.write("Status: ⚠️ MODERATE - Some context loss detected\n")
                else:
                    f.write("Status: ❌ SIGNIFICANT - Context loss may affect meaning\n")
                
                f.write("\n")
            
            f.write("=" * 80 + "\n")
            f.write("INTERPRETATION GUIDE\n")
            f.write("=" * 80 + "\n")
            f.write("""
- 90%+ similarity: Chunk-by-chunk is working well
- 80-90% similarity: Minor variations, usually acceptable
- 70-80% similarity: Consider enabling/tuning context-aware translation
- <70% similarity: Significant context loss, review needed

Common causes of low similarity:
1. Pronoun resolution (he/she/it translated differently)
2. Theological term consistency (same word translated differently)
3. Sentence flow and connectors
4. Gender/number agreement across chunks

If similarity is low, review the specific differences above to determine
if they affect theological meaning.
""")
        
        print(f"   Context comparison saved: {comparison_filename}")
        return comparison_filename
    
    def _save_glossary_report(self, base_filename: str):
        """Save glossary corrections report (Mode 13 - Option B)
        
        Args:
            base_filename: Base filename (without extension) for the report
        """
        if not self.glossary_corrections_log:
            print("   No glossary corrections were made")
            return None
        
        report_filename = f"{base_filename}_glossary_corrections.txt"
        
        # Count total corrections
        total_corrections = sum(
            len(entry['corrections'].get(lang, []))
            for entry in self.glossary_corrections_log
            for lang in entry['corrections']
        )
        
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("GLOSSARY CORRECTIONS REPORT (Mode 13 - Option B)\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Segments with Corrections: {len(self.glossary_corrections_log)}\n")
            f.write(f"Total Corrections Made: {total_corrections}\n")
            f.write(f"Glossary Size: {len(THEOLOGICAL_GLOSSARY)} terms\n\n")
            
            f.write("=" * 80 + "\n")
            f.write("CORRECTION DETAILS\n")
            f.write("=" * 80 + "\n\n")
            
            for entry in self.glossary_corrections_log:
                f.write(f"--- [{entry['timestamp'].split('T')[1][:8]}] ---\n")
                f.write(f"Source: {entry['source_text'][:80]}...\n")
                
                for lang_name, corrections in entry['corrections'].items():
                    for corr in corrections:
                        f.write(f"  {lang_name}: '{corr['original']}' → '{corr['corrected']}' (PT: {corr['portuguese']})\n")
                f.write("\n")
            
            # Summary by term
            f.write("=" * 80 + "\n")
            f.write("CORRECTION FREQUENCY BY TERM\n")
            f.write("=" * 80 + "\n\n")
            
            term_counts = {}
            for entry in self.glossary_corrections_log:
                for lang_name, corrections in entry['corrections'].items():
                    for corr in corrections:
                        key = f"{corr['original']} → {corr['corrected']}"
                        term_counts[key] = term_counts.get(key, 0) + 1
            
            for term, count in sorted(term_counts.items(), key=lambda x: -x[1]):
                f.write(f"  {count:3d}x  {term}\n")
        
        print(f"   Glossary corrections saved: {report_filename}")
        return report_filename
    
    def _save_context_differences_report(self, base_filename: str):
        """Save async context differences report (Mode 13 - Option A)
        
        Args:
            base_filename: Base filename (without extension) for the report
        """
        if not self.async_context_differences:
            print("   No significant context differences found")
            return None
        
        report_filename = f"{base_filename}_context_differences.txt"
        
        # Count by severity
        high_count = sum(1 for d in self.async_context_differences 
                        for lang_diff in d['differences'].values() 
                        if lang_diff.get('severity') == 'HIGH')
        medium_count = sum(1 for d in self.async_context_differences 
                          for lang_diff in d['differences'].values() 
                          if lang_diff.get('severity') == 'MEDIUM')
        low_count = sum(1 for d in self.async_context_differences 
                       for lang_diff in d['differences'].values() 
                       if lang_diff.get('severity') == 'LOW')
        
        with open(report_filename, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("CONTEXT DIFFERENCES REPORT (Mode 13 - Option A)\n")
            f.write("Async Context Comparison Results\n")
            f.write("=" * 80 + "\n\n")
            
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total Segments with Differences: {len(self.async_context_differences)}\n")
            f.write(f"Severity Breakdown:\n")
            f.write(f"  🔴 HIGH (pronoun changes): {high_count}\n")
            f.write(f"  🟡 MEDIUM (>30% different): {medium_count}\n")
            f.write(f"  🟢 LOW (15-30% different): {low_count}\n\n")
            
            # Show HIGH severity first
            f.write("=" * 80 + "\n")
            f.write("🔴 HIGH SEVERITY - Pronoun/Meaning Changes (Review Recommended)\n")
            f.write("=" * 80 + "\n\n")
            
            high_items = [d for d in self.async_context_differences 
                         if any(diff.get('severity') == 'HIGH' for diff in d['differences'].values())]
            
            if high_items:
                for item in high_items:
                    f.write(f"--- Segment {item['segment_id']} [{item['timestamp'].split('T')[1][:8]}] ---\n")
                    f.write(f"Source: {item['source_text']}\n")
                    if item.get('context'):
                        f.write(f"Context: {item['context']}\n")
                    
                    for lang_name, diff in item['differences'].items():
                        if diff.get('severity') == 'HIGH':
                            f.write(f"\n  {lang_name}:\n")
                            f.write(f"    Fast:    {diff['fast_translation']}\n")
                            f.write(f"    Context: {diff['context_translation']}\n")
                            if diff.get('pronoun_details'):
                                f.write(f"    Pronoun: {', '.join(diff['pronoun_details'])}\n")
                    f.write("\n")
            else:
                f.write("  None found - Good!\n\n")
            
            # Show MEDIUM severity
            f.write("=" * 80 + "\n")
            f.write("🟡 MEDIUM SEVERITY - Significant Differences\n")
            f.write("=" * 80 + "\n\n")
            
            medium_items = [d for d in self.async_context_differences 
                          if any(diff.get('severity') == 'MEDIUM' for diff in d['differences'].values())]
            
            if medium_items:
                for item in medium_items[:20]:  # Limit to first 20
                    f.write(f"--- Segment {item['segment_id']} ---\n")
                    f.write(f"Source: {item['source_text'][:60]}...\n")
                    for lang_name, diff in item['differences'].items():
                        if diff.get('severity') == 'MEDIUM':
                            f.write(f"  Difference: {diff['difference_ratio']*100:.0f}%\n")
                    f.write("\n")
                if len(medium_items) > 20:
                    f.write(f"  ... and {len(medium_items) - 20} more\n\n")
            else:
                f.write("  None found\n\n")
            
            # Summary
            f.write("=" * 80 + "\n")
            f.write("INTERPRETATION\n")
            f.write("=" * 80 + "\n")
            f.write("""
HIGH severity items indicate pronoun differences (he/she/it/him/her) between
fast translation and context-aware translation. These may affect theological
meaning and should be reviewed by a bilingual person.

MEDIUM severity items have >30% word differences, which may indicate:
- Different sentence structure
- Alternative word choices
- Missing or added connectors

LOW severity items have 15-30% differences, usually acceptable variations.

If you see many HIGH severity items, consider:
1. Building a specialized glossary for problematic terms
2. Reviewing source audio for clarity
3. Checking if specific phrases consistently cause issues
""")
        
        print(f"   Context differences saved: {report_filename}")
        return report_filename
    
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
    
    def _run_dual_stream_mode(self, config, streaming_config):
        """
        Run in dual stream mode for maximum coverage.
        
        Uses DualStreamManager to run two overlapping streams,
        eliminating gaps during stream restarts.
        
        PRIMARY/BACKUP MODEL:
        - Stream A = Primary (outputs to display)
        - Stream B = Backup (buffers, releases during gaps)
        """
        print("\n" + "=" * 60)
        print("   DUAL STREAM MODE (Mode 16) - PRIMARY/BACKUP MODEL")
        print("=" * 60)
        
        # Get dual stream settings
        stream_b_delay = self.test_config.get('stream_b_delay_seconds', 150)
        gap_threshold = self.test_config.get('gap_threshold_seconds', 3.0)
        buffer_duration = self.test_config.get('buffer_duration_seconds', 30.0)
        
        # Create dual stream manager with Primary/Backup model
        dual_manager = DualStreamManager(
            speech_client=self.speech_client,
            config=config,
            streaming_config=streaming_config,
            audio_streamer=self.audio_streamer,
            stream_b_delay=stream_b_delay,
            gap_threshold=gap_threshold,
            buffer_duration=buffer_duration
        )
        
        # Store reference for cleanup
        self.dual_stream_manager = dual_manager
        
        # Start dual streams
        dual_manager.start()
        
        print(f"   Waiting for first recognition result...")
        
        # Main processing loop
        while self.display.is_running:
            # Check if file playback finished
            if self.audio_source == "file" and hasattr(self.audio_streamer, 'is_finished'):
                if self.audio_streamer.is_finished and self.audio_streamer.audio_queue.empty():
                    # Wait a bit for final results from both streams
                    time.sleep(2)
                    
                    # Record when audio ended
                    if self.audio_end_time is None:
                        self.audio_end_time = datetime.now()
                        
                        # Get dual stream stats
                        stats = dual_manager.get_statistics()
                        print(f"\nFINISHED - Audio file playback complete")
                        print(f"   === PRIMARY/BACKUP STATISTICS ===")
                        print(f"   Stream A (PRIMARY) segments: {stats['stream_a_segments']}")
                        print(f"   Stream B (BACKUP) segments released: {stats['stream_b_segments']}")
                        print(f"   Stream B segments buffered (total): {stats['stream_b_buffered']}")
                        print(f"   Gaps filled by backup: {stats['gaps_filled']}")
                        print(f"   Stream A restarts: {stats['stream_a_restarts']}")
                        print(f"   Stream B restarts: {stats['stream_b_restarts']}")
                        print(f"   Current buffer size: {stats['buffer_size']}")
                        print(f"   Waiting for display queue to drain...")
                    
                    # Wait for display queue to empty
                    if self.display.text_queue.empty():
                        self.final_display_time = datetime.now()
                        queue_drain_time = (self.final_display_time - self.audio_end_time).total_seconds()
                        print(f"\nOK - Queue drained at {self.final_display_time.strftime('%H:%M:%S')}")
                        print(f"   QUEUE DRAIN TIME: {queue_drain_time:.1f} seconds")
                        
                        time.sleep(2)
                        dual_manager.stop()
                        self.display.root.after(0, self._stop)
                        break
                    else:
                        time.sleep(0.5)
                        continue
            
            if self.is_paused:
                dual_manager.is_paused = True
                time.sleep(0.5)
                continue
            else:
                dual_manager.is_paused = False
            
            # Get next result from dual stream manager
            result = dual_manager.get_next_result(timeout=0.5)
            
            if result is None:
                continue
            
            transcript = result['transcript']
            stream_id = result['stream_id']
            
            # Apply post-recognition corrections
            transcript = self.apply_post_recognition_corrections(transcript)
            
            # Track first result timing
            if self.first_result_time is None:
                self.first_result_time = datetime.now()
                time_to_first = (self.first_result_time - self.stream_start_time).total_seconds()
                print(f"\n   FIRST RESULT received at {self.first_result_time.strftime('%H:%M:%S')}")
                print(f"   Time to first result: {time_to_first:.1f} seconds")
                print("-" * 50)
            
            word_count = len(transcript.split())
            
            # Create segment data
            self.segment_counter += 1
            original_segment_id = self.segment_counter
            timestamp_spoken = result['timestamp']
            timestamp_recognized = datetime.now()
            
            # Track last segment time
            self.last_segment_time = timestamp_recognized
            
            # Skip if hard paused
            if self.is_hard_paused:
                print(f"   [HARD PAUSED] Skipping segment {original_segment_id}")
                continue
            
            # Translate
            translations = self.translate_to_multiple(transcript)
            timestamp_translated = datetime.now()
            
            # Check if chunk splitting is needed
            chunk_split_enabled = self.test_config.get('chunk_split_enabled', False)
            chunk_threshold = self.test_config.get('chunk_split_threshold', 40)
            chunk_min = self.test_config.get('chunk_min_size', 15)
            
            if chunk_split_enabled and word_count > chunk_threshold:
                # Split the text into chunks
                original_chunks = self.split_text_into_chunks(transcript, chunk_threshold, chunk_min)
                
                for chunk_num, chunk_text in enumerate(original_chunks, 1):
                    chunk_word_count = len(chunk_text.split())
                    
                    # Translate chunk
                    chunk_translations = self.translate_to_multiple(chunk_text)
                    chunk_timestamp = datetime.now()
                    
                    # Create segment for this chunk
                    chunk_segment = SegmentData(
                        segment_id=self.segment_counter,
                        text_original=chunk_text,
                        text_translated=chunk_translations,
                        word_count=chunk_word_count,
                        timestamp_spoken=timestamp_spoken,
                        timestamp_recognized=timestamp_recognized,
                        timestamp_translated=chunk_timestamp,
                        timestamp_queued=datetime.now(),
                        queue_depth_at_queue=self.display.text_queue.qsize(),
                        original_segment_id=original_segment_id,
                        chunk_number=chunk_num,
                        total_chunks=len(original_chunks),
                        was_split=True,
                        original_word_count=word_count,
                    )
                    
                    # Log to console
                    print(f"[Stream {stream_id}] [{datetime.now().strftime('%H:%M:%S')}] Chunk {chunk_num}/{len(original_chunks)}: {chunk_text[:60]}...")
                    for lang_name, translation in chunk_translations.items():
                        print(f"   -> {lang_name}: {translation[:60]}...")
                    
                    # Build display list
                    display_translations = [
                        chunk_translations.get(lang[1], "") 
                        for lang in self.display_languages
                    ]
                    self.display.add_translation(display_translations, chunk_segment, False)
                    
                    # Write to CSV
                    self._write_csv_row(chunk_segment)
                    
                    # Add to session
                    self.session.add_segment(chunk_segment)
                    
                    # Log to file
                    if self.output_file:
                        self.output_file.write(f"[{datetime.now().strftime('%H:%M:%S')}] Stream {stream_id} Segment {self.segment_counter} (chunk {chunk_num}/{len(original_chunks)})\n")
                        self.output_file.write(f"  Text: {chunk_text}\n\n")
                        self.output_file.flush()
                    
                    self.segment_counter += 1
            else:
                # No splitting needed
                segment = SegmentData(
                    segment_id=original_segment_id,
                    text_original=transcript,
                    text_translated=translations,
                    word_count=word_count,
                    timestamp_spoken=timestamp_spoken,
                    timestamp_recognized=timestamp_recognized,
                    timestamp_translated=timestamp_translated,
                    timestamp_queued=datetime.now(),
                    queue_depth_at_queue=self.display.text_queue.qsize(),
                )
                
                # Log to console
                print(f"[Stream {stream_id}] [{datetime.now().strftime('%H:%M:%S')}] {transcript}")
                for lang_name, translation in translations.items():
                    print(f"   -> {lang_name}: {translation}")
                
                # Build display list
                display_translations = [
                    translations.get(lang[1], "") 
                    for lang in self.display_languages
                ]
                self.display.add_translation(display_translations, segment, False)
                
                # Write to CSV
                self._write_csv_row(segment)
                
                # Add to session
                self.session.add_segment(segment)
                
                # Log to file
                if self.output_file:
                    self.output_file.write(f"[{datetime.now().strftime('%H:%M:%S')}] Stream {stream_id} Segment {segment.segment_id}\n")
                    self.output_file.write(f"  Latency: {segment.latency_recognition:.2f}s (recog) + {segment.latency_translation:.2f}s (trans)\n")
                    self.output_file.write(f"  Queue depth: {segment.queue_depth_at_queue}\n")
                    self.output_file.write(f"  Text: {transcript}\n\n")
                    self.output_file.flush()
                
                print("-" * 50)
        
        # Cleanup
        dual_manager.stop()
    
    def _audio_processing(self):
        """Audio processing with full instrumentation"""
        
        # Determine model based on test config
        if self.test_config.get('use_default_model', False):
            speech_model = "default"
            print("   Using 'default' model for minimal latency")
        elif self.test_config.get('use_short_model', False):
            speech_model = "latest_short"
            print("   Using 'latest_short' model for faster recognition")
        else:
            speech_model = "latest_long"
            print("   Using 'latest_long' model for accuracy")
        
        # Determine if we should enable interim results at API level
        # This forces Google to process more frequently even if we don't display interim results
        api_interim = self.test_config.get('api_interim_results', False) or \
                      self.test_config.get('use_interim_results', False)
        
        if self.test_config.get('api_interim_results', False):
            print("   API interim results ENABLED (forces faster processing)")
        
        # Check for minimal latency settings
        use_enhanced = not self.test_config.get('disable_enhanced', False)
        use_punctuation = not self.test_config.get('disable_punctuation', False)
        use_speech_context = not self.test_config.get('disable_speech_context', False)
        
        if self.test_config.get('disable_enhanced', False):
            print("   Enhanced model DISABLED (faster processing)")
        if self.test_config.get('disable_punctuation', False):
            print("   Auto-punctuation DISABLED (faster returns)")
        if self.test_config.get('disable_speech_context', False):
            print("   Speech context hints DISABLED (faster processing)")
        else:
            print("   Speech context hints ENABLED (better theological term recognition)")
        
        # Build speech contexts only if enabled
        if use_speech_context:
            speech_contexts = [speech.SpeechContext(phrases=self.SERMON_CONTEXT_HINTS, boost=15)]
        else:
            speech_contexts = []
        
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=self.source_language[0],
            enable_automatic_punctuation=use_punctuation,
            use_enhanced=use_enhanced,
            model=speech_model,
            speech_contexts=speech_contexts,
        )
        
        # Check for voice activity timeout settings
        use_voice_timeout = self.test_config.get('use_voice_activity_timeout', False)
        
        if use_voice_timeout:
            speech_start_sec = self.test_config.get('speech_start_timeout_sec', 5)
            speech_end_sec = self.test_config.get('speech_end_timeout_sec', 1)
            
            print(f"   Voice Activity Timeout ENABLED")
            print(f"      Speech start timeout: {speech_start_sec} seconds")
            print(f"      Speech end timeout: {speech_end_sec} seconds (forces faster finalization)")
            
            voice_timeout = speech.StreamingRecognitionConfig.VoiceActivityTimeout(
                speech_start_timeout=duration_pb2.Duration(seconds=speech_start_sec),
                speech_end_timeout=duration_pb2.Duration(seconds=speech_end_sec),
            )
            
            streaming_config = speech.StreamingRecognitionConfig(
                config=config,
                interim_results=api_interim,
                single_utterance=False,
                voice_activity_timeout=voice_timeout,
            )
        else:
            streaming_config = speech.StreamingRecognitionConfig(
                config=config,
                interim_results=api_interim,
                single_utterance=False
            )
        
        self.audio_streamer.start_stream()
        
        # Track streaming statistics
        self.stream_start_time = datetime.now()
        
        print(f"\n   Streaming started at {self.stream_start_time.strftime('%H:%M:%S')}")
        
        # Check if dual stream mode is enabled (Mode 16)
        if self.test_config.get('dual_stream_enabled', False):
            self._run_dual_stream_mode(config, streaming_config)
            return
        
        print(f"   Waiting for first recognition result...")
        
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
                        
                        # Apply post-recognition corrections to fix common misrecognitions
                        transcript = self.apply_post_recognition_corrections(transcript)
                        
                        is_final = result.is_final
                        word_count = len(transcript.split())
                        
                        # ============================================================
                        # HYBRID BUFFER MODE (Mode 17)
                        # ============================================================
                        # If hybrid buffer is enabled, collect FINAL results until:
                        # 1. Sentence ending detected (. ? !)
                        # 2. Word count reaches threshold
                        # 3. Timeout elapsed
                        # 
                        # IMPORTANT: Only process FINAL results to avoid duplicates!
                        # Interim results are tracked for restart flush only.
                        # ============================================================
                        if self.hybrid_buffer is not None:
                            # ALWAYS track the latest content for restart recovery
                            # (whether interim or FINAL - we want the most recent content)
                            if not is_final:
                                # Save interim for potential restart recovery
                                self.last_interim_for_restart = transcript
                                self.last_interim_word_count = word_count
                                print(f"(interim) {word_count} words - waiting for FINAL...", end='\r')
                                continue
                            else:
                                # FINAL received - DON'T clear interim tracker yet!
                                # Keep it available in case restart happens right after.
                                # The FINAL content is the same as the last interim, so we
                                # can keep the interim tracker as-is for restart recovery.
                                # It will be cleared after successful restart flush.
                                pass
                            
                            # Add FINAL result to buffer
                            should_flush, buffered_text, flush_reason = self.hybrid_buffer.add_fragment(
                                transcript, is_final
                            )
                            
                            if not should_flush:
                                # Not ready to flush - show buffer status
                                # Also update the restart tracker with this FINAL
                                self.last_interim_for_restart = transcript
                                self.last_interim_word_count = word_count
                                status = self.hybrid_buffer.get_buffer_status()
                                print(f"\n[BUFFER] Added FINAL: {word_count} words | "
                                      f"Buffer: {status['words']} words, {status['elapsed_seconds']:.1f}s elapsed")
                                continue
                            else:
                                # Buffer is ready to flush - NOW we can clear the restart tracker
                                # because we're about to display this content
                                self.last_interim_for_restart = None
                                self.last_interim_word_count = 0
                                
                                transcript = buffered_text
                                word_count = len(transcript.split())
                                is_final = True  # Treat buffered content as final
                                
                                print(f"\n[BUFFER FLUSH] {flush_reason.upper()}: {word_count} words")
                                
                                # Skip early interim logic since we're using buffer
                                # Fall through to translation
                        
                        # Check for early interim display mode (ONLY if not using hybrid buffer)
                        elif self.test_config.get('early_interim_display', False):
                            early_interim_threshold = self.test_config.get('early_interim_word_threshold', 20)
                            
                            # Handle interim results
                            if not is_final:
                                # Early interim display mode - display after threshold words
                                new_word_count = word_count - self.interim_words_displayed
                                
                                if new_word_count >= early_interim_threshold:
                                    # We have enough NEW words to display
                                    words = transcript.split()
                                    
                                    # Extract only the NEW words (not already displayed)
                                    new_text = ' '.join(words[self.interim_words_displayed:])
                                    
                                    print(f"(early-interim) {word_count} total, displaying {new_word_count} NEW words")
                                    
                                    # Update tracking BEFORE processing
                                    self.interim_words_displayed = word_count
                                    self.interim_text_displayed = transcript
                                    
                                    # Use new_text for translation and display
                                    transcript = new_text
                                    word_count = len(transcript.split())
                                    # Continue to process this for display
                                else:
                                    # Not enough NEW words yet
                                    print(f"(interim) {word_count} total, {new_word_count} new - waiting for {early_interim_threshold} new...", end='\r')
                                    continue
                            else:
                                # FINAL result arrived with early interim enabled
                                if self.interim_words_displayed > 0:
                                    # We displayed interim, now show remaining NEW words only
                                    new_word_count = word_count - self.interim_words_displayed
                                    
                                    if new_word_count > 2:  # Only display if meaningful new content
                                        print(f"[Final] [{datetime.now().strftime('%H:%M:%S')}] +{new_word_count} new words from final")
                                        # Extract just the NEW words
                                        words = transcript.split()
                                        transcript = ' '.join(words[self.interim_words_displayed:])
                                        word_count = len(transcript.split())
                                    else:
                                        print(f"[Final] [{datetime.now().strftime('%H:%M:%S')}] Final received (+{new_word_count} words, skipping)")
                                        # Track skipped FINAL content
                                        self.skipped_finals_count += 1
                                        self.skipped_finals_words += new_word_count
                                        # Reset tracking for next utterance
                                        self.interim_words_displayed = 0
                                        self.interim_text_displayed = ""
                                        continue  # Skip since we already displayed most of it
                                
                                # Reset interim tracking for next utterance
                                self.interim_words_displayed = 0
                                self.interim_text_displayed = ""
                        
                        else:
                            # Standard mode (no hybrid buffer, no early interim)
                            if not is_final:
                                if not self.test_config.get('use_interim_results'):
                                    print(f"(interim) {transcript}", end='\r')
                                    continue
                        
                        # Track first result timing
                        if self.first_result_time is None:
                            self.first_result_time = datetime.now()
                            time_to_first = (self.first_result_time - self.stream_start_time).total_seconds()
                            print(f"\n   FIRST RESULT received at {self.first_result_time.strftime('%H:%M:%S')}")
                            print(f"   Time to first result: {time_to_first:.1f} seconds")
                            print("-" * 50)
                        
                        # Create base segment data
                        self.segment_counter += 1
                        original_segment_id = self.segment_counter
                        timestamp_spoken = self.last_audio_timestamp or batch_start_time
                        timestamp_recognized = datetime.now()
                        original_word_count = len(transcript.split())
                        
                        # Track last segment time for restart gap calculation
                        self.last_segment_time = timestamp_recognized
                        
                        # Skip translation if hard paused (no API calls during hard pause)
                        if self.is_hard_paused:
                            print(f"   [HARD PAUSED] Skipping translation for segment {original_segment_id}")
                            continue
                        
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
                        self.stream_restart_count += 1
                        restart_time = datetime.now()
                        
                        # ============================================================
                        # FLUSH HYBRID BUFFER ON RESTART (Option C)
                        # ============================================================
                        # When stream restarts, immediately flush any buffered content
                        # AND recover any pending interim content to prevent loss.
                        # ============================================================
                        if self.hybrid_buffer is not None:
                            # First, flush any buffered FINAL content
                            has_content, buffered_text = self.hybrid_buffer.flush(reason='restart')
                            
                            # Debug: Log state before recovery attempt
                            print(f"\n[RESTART DEBUG] Buffer had content: {has_content}")
                            print(f"[RESTART DEBUG] Last interim available: {self.last_interim_for_restart is not None}")
                            print(f"[RESTART DEBUG] Last interim words: {self.last_interim_word_count}")
                            
                            # Also recover the last interim if we have one (this is the key fix!)
                            # Lowered threshold from 5 to 3 words to capture more content
                            if self.last_interim_for_restart and self.last_interim_word_count >= 3:
                                # Combine buffer content with last interim
                                if has_content and buffered_text:
                                    combined_text = buffered_text + " " + self.last_interim_for_restart
                                else:
                                    combined_text = self.last_interim_for_restart
                                    has_content = True
                                
                                print(f"[RESTART FLUSH] Recovering {self.last_interim_word_count} words from last interim")
                                buffered_text = combined_text
                                
                                # Track this as a restart flush
                                self.hybrid_buffer.flushes_by_restart += 1
                                
                                # Clear the interim tracker
                                self.last_interim_for_restart = None
                                self.last_interim_word_count = 0
                            
                            if has_content and buffered_text:
                                word_count = len(buffered_text.split())
                                print(f"[RESTART FLUSH] Total flushed: {word_count} words")
                                
                                # Translate and display the buffered content
                                translations = self.translate_to_multiple(buffered_text)
                                timestamp_translated = datetime.now()
                                
                                self.segment_counter += 1
                                segment = SegmentData(
                                    segment_id=self.segment_counter,
                                    text_original=buffered_text,
                                    text_translated=translations,
                                    word_count=word_count,
                                    timestamp_spoken=self.last_audio_timestamp or restart_time,
                                    timestamp_recognized=restart_time,
                                    timestamp_translated=timestamp_translated,
                                    timestamp_queued=datetime.now(),
                                    is_interim=False,
                                    queue_depth_at_queue=self.display.text_queue.qsize()
                                )
                                
                                # Display
                                display_translations = [
                                    translations.get(lang[1], "") 
                                    for lang in self.display_languages
                                ]
                                self.display.add_translation(display_translations, segment, False)
                                
                                # Write to CSV and session
                                self._write_csv_row(segment)
                                self.session.add_segment(segment)
                                
                                # Update last segment time to reduce gap calculation
                                self.last_segment_time = datetime.now()
                                
                                for lang_name, translation in translations.items():
                                    print(f"   -> {lang_name}: {translation[:80]}...")
                        
                        # Calculate gap since last segment
                        if self.last_segment_time:
                            gap_duration = (restart_time - self.last_segment_time).total_seconds()
                            self.restart_gaps.append({
                                'restart_num': self.stream_restart_count,
                                'restart_time': restart_time,
                                'last_segment_time': self.last_segment_time,
                                'gap_duration': gap_duration
                            })
                            print(f"\nWARNING: Stream timeout #{self.stream_restart_count} - restarting...")
                            print(f"   Gap since last segment: {gap_duration:.1f} seconds")
                            print(f"   (This is normal - Google limits streams to ~5 minutes)")
                        else:
                            print(f"\nWARNING: Stream timeout #{self.stream_restart_count} - restarting...")
                            print(f"   (This is normal - Google limits streams to ~5 minutes)")
                        
                        # Reset interim tracking on stream restart
                        self.interim_words_displayed = 0
                        self.interim_text_displayed = ""
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
        
        # ============================================================
        # FLUSH HYBRID BUFFER ON STOP (Option C)
        # ============================================================
        # When test stops, flush any remaining buffered content
        # to prevent content loss at the end of the audio.
        # ============================================================
        if self.hybrid_buffer is not None:
            has_content, buffered_text = self.hybrid_buffer.flush(reason='final')
            if has_content and buffered_text and len(buffered_text.split()) >= 3:
                print(f"\n[FINAL FLUSH] Flushing remaining buffer: {len(buffered_text.split())} words")
                
                # Translate and display the buffered content
                translations = self.translate_to_multiple(buffered_text)
                timestamp_translated = datetime.now()
                
                self.segment_counter += 1
                segment = SegmentData(
                    segment_id=self.segment_counter,
                    text_original=buffered_text,
                    text_translated=translations,
                    word_count=len(buffered_text.split()),
                    timestamp_spoken=self.last_audio_timestamp or datetime.now(),
                    timestamp_recognized=datetime.now(),
                    timestamp_translated=timestamp_translated,
                    timestamp_queued=datetime.now(),
                    is_interim=False,
                    queue_depth_at_queue=self.display.text_queue.qsize()
                )
                
                # Display
                display_translations = [
                    translations.get(lang[1], "") 
                    for lang in self.display_languages
                ]
                self.display.add_translation(display_translations, segment, False)
                
                # Write to CSV and session
                self._write_csv_row(segment)
                self.session.add_segment(segment)
                
                for lang_name, translation in translations.items():
                    print(f"   -> {lang_name}: {translation[:80]}...")
        
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
    
    def _get_hybrid_buffer_stats(self) -> str:
        """Get hybrid buffer statistics as formatted string for summary."""
        if not self.hybrid_buffer:
            return ""
        
        stats = self.hybrid_buffer.get_statistics()
        
        return f"""HYBRID BUFFER STATISTICS
------------------------
Total Flushes:        {stats['total_flushes']}
  By Sentence End:    {stats['flushes_by_sentence']} (. ? !)
  By Word Count:      {stats['flushes_by_words']} (≥{self.test_config.get('buffer_max_words', 50)} words)
  By Timeout:         {stats['flushes_by_timeout']} (≥{self.test_config.get('buffer_timeout_seconds', 15)}s)
  By Restart:         {stats['flushes_by_restart']} (stream restart - prevents content loss)
  By Final:           {stats['flushes_by_final']} (test end - captures remaining content)

"""
    
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
        
        # Recognition latency analysis
        recognition_latencies = [s.latency_recognition for s in self.session.segments if not s.was_split or s.chunk_number == 1]
        if recognition_latencies:
            avg_recog = sum(recognition_latencies) / len(recognition_latencies)
            max_recog = max(recognition_latencies)
            min_recog = min(recognition_latencies)
            
            # Trend analysis for recognition
            if len(recognition_latencies) > 4:
                first_half_recog = recognition_latencies[:len(recognition_latencies)//2]
                second_half_recog = recognition_latencies[len(recognition_latencies)//2:]
                first_avg_recog = sum(first_half_recog) / len(first_half_recog)
                second_avg_recog = sum(second_half_recog) / len(second_half_recog)
                recog_trend = second_avg_recog - first_avg_recog
            else:
                first_avg_recog = 0
                second_avg_recog = 0
                recog_trend = 0
            
            recog_trend_str = "INCREASING" if recog_trend > 5 else "STABLE" if abs(recog_trend) <= 5 else "DECREASING"
            
            # Recognition coverage analysis - detect if Google is skipping audio
            # Count total words recognized (from original segments, not chunks)
            total_words_recognized = sum(s.original_word_count if s.original_word_count else s.word_count 
                                         for s in self.session.segments 
                                         if not s.was_split or s.chunk_number == 1)
            
            # Estimate expected words based on audio duration
            # Typical sermon speaking rate: 120-150 words per minute
            # Using 130 wpm as baseline (conservative estimate)
            audio_duration_minutes = self.session.duration_seconds / 60
            expected_words_low = audio_duration_minutes * 100  # Slow speaker
            expected_words_mid = audio_duration_minutes * 130  # Average speaker
            expected_words_high = audio_duration_minutes * 160  # Fast speaker
            
            # Calculate coverage percentage (using mid estimate)
            coverage_percent = (total_words_recognized / expected_words_mid * 100) if expected_words_mid > 0 else 0
            
            # Determine coverage status
            if coverage_percent >= 80:
                coverage_status = "EXCELLENT - Google captured most/all speech"
            elif coverage_percent >= 60:
                coverage_status = "GOOD - Minor gaps possible"
            elif coverage_percent >= 40:
                coverage_status = "WARNING - Google may be skipping significant portions"
            else:
                coverage_status = "POOR - Google likely skipping large portions of audio"
            
            recognition_section = f"""
{'='*70}
RECOGNITION LATENCY ANALYSIS (Google Speech API)
{'='*70}
Average Recognition Time: {avg_recog:.2f} seconds
Maximum Recognition Time: {max_recog:.2f} seconds
Minimum Recognition Time: {min_recog:.2f} seconds

Recognition Trend:
  First Half Average:  {first_avg_recog:.2f} seconds
  Second Half Average: {second_avg_recog:.2f} seconds
  Trend: {recog_trend:+.2f} seconds ({recog_trend_str})

{'='*70}
RECOGNITION COVERAGE ANALYSIS (Is Google Skipping Audio?)
{'='*70}
Audio Duration: {audio_duration_minutes:.1f} minutes

Expected Words (based on speaking rate):
  Slow speaker (100 wpm):   {expected_words_low:.0f} words
  Average speaker (130 wpm): {expected_words_mid:.0f} words
  Fast speaker (160 wpm):   {expected_words_high:.0f} words

Actual Words Recognized: {total_words_recognized} words
Coverage (vs average):   {coverage_percent:.1f}%

Status: {coverage_status}

Note: If coverage is below 60%, Google may be dropping audio segments.
This can happen with poor audio quality, heavy accents, or background noise.
"""
        else:
            recognition_section = ""
        
        # Calculate time to first result
        if self.stream_start_time and self.first_result_time:
            time_to_first_result = (self.first_result_time - self.stream_start_time).total_seconds()
            time_to_first_str = f"{time_to_first_result:.1f} seconds"
        else:
            time_to_first_str = "Not measured"
        
        # Check for fast recognition settings
        fast_recognition = self.test_config.get('force_faster_recognition', False)
        use_short_model = self.test_config.get('use_short_model', False)
        use_default_model = self.test_config.get('use_default_model', False)
        api_interim = self.test_config.get('api_interim_results', False)
        disable_enhanced = self.test_config.get('disable_enhanced', False)
        disable_punctuation = self.test_config.get('disable_punctuation', False)
        disable_speech_context = self.test_config.get('disable_speech_context', False)
        
        if disable_enhanced:
            # Mode 10/12 - Minimal Latency variants
            model_name = "default" if use_default_model else ("latest_short" if use_short_model else "latest_long")
            hints_status = "OFF" if disable_speech_context else "ON"
            fast_recog_str = f"MINIMAL LATENCY (model: {model_name}, enhanced: OFF, punctuation: OFF, hints: {hints_status})"
        elif fast_recognition:
            model_name = "latest_short" if use_short_model else "latest_long"
            fast_recog_str = f"Enabled (model: {model_name}, API interim: {api_interim})"
        else:
            fast_recog_str = "Disabled"
        
        # Voice activity timeout settings
        use_voice_timeout = self.test_config.get('use_voice_activity_timeout', False)
        if use_voice_timeout:
            speech_end_sec = self.test_config.get('speech_end_timeout_sec', 1)
            voice_timeout_str = f"Enabled (speech_end_timeout: {speech_end_sec}s)"
        else:
            voice_timeout_str = "Disabled"
        
        # Early interim display settings
        early_interim_enabled = self.test_config.get('early_interim_display', False)
        if early_interim_enabled:
            early_threshold = self.test_config.get('early_interim_word_threshold', 20)
            early_interim_str = f"Enabled (display after {early_threshold} words)"
        else:
            early_interim_str = "Disabled"
        
        # Build restart gap analysis section
        if self.restart_gaps:
            total_gap_time = sum(g['gap_duration'] for g in self.restart_gaps)
            avg_gap = total_gap_time / len(self.restart_gaps)
            estimated_words_lost = int(total_gap_time * 130 / 60)  # Assume 130 wpm
            
            restart_details = []
            for gap in self.restart_gaps:
                restart_details.append(
                    f"  Restart #{gap['restart_num']}: {gap['gap_duration']:.1f}s gap "
                    f"(at {gap['restart_time'].strftime('%H:%M:%S')})"
                )
            restart_details_str = '\n'.join(restart_details)
            
            restart_gap_section = f"""
RESTART GAP ANALYSIS (Audio Lost During Stream Restarts)
{'='*70}
Total Restarts:        {len(self.restart_gaps)}
Total Gap Time:        {total_gap_time:.1f} seconds
Average Gap:           {avg_gap:.1f} seconds
Estimated Words Lost:  ~{estimated_words_lost} words (at 130 wpm)

RESTART DETAILS
---------------
{restart_details_str}

Note: Google Speech API has a ~5 minute streaming limit.
Stream restarts are unavoidable; gaps represent audio that was not processed.
{'='*70}
"""
        else:
            restart_gap_section = ""
        
        # =================================================================
        # BUILD KEY METRICS OVERVIEW SECTION
        # =================================================================
        
        # Calculate content loss
        words_lost_restarts = int(sum(g['gap_duration'] for g in self.restart_gaps) * 130 / 60) if self.restart_gaps else 0
        words_lost_skipped = self.skipped_finals_words
        total_words_lost = words_lost_restarts + words_lost_skipped
        
        # Get expected words for percentage calculation
        audio_duration_minutes = self.session.duration_seconds / 60
        expected_words = audio_duration_minutes * 130  # Average speaker
        content_loss_percent = (total_words_lost / expected_words * 100) if expected_words > 0 else 0
        
        # Calculate coverage if we have recognition data
        total_words_recognized = sum(s.original_word_count if s.original_word_count else s.word_count 
                                     for s in self.session.segments 
                                     if not s.was_split or s.chunk_number == 1)
        coverage_pct = (total_words_recognized / expected_words * 100) if expected_words > 0 else 0
        
        # Calculate percentages for distribution
        total_waits_for_pct = len(queue_wait_times) if queue_wait_times else 1
        under_3_pct = (under_3 / total_waits_for_pct) * 100
        over_12_pct = (over_12 / total_waits_for_pct) * 100
        
        # Determine emoji status for each metric
        # Duration - informational only
        duration_emoji = "⏱️"
        
        # Coverage
        if coverage_pct >= 80:
            coverage_emoji = "✅"
        elif coverage_pct >= 60:
            coverage_emoji = "⚠️"
        else:
            coverage_emoji = "❌"
        
        # Average Wait
        if avg_queue_wait <= 2:
            avg_wait_emoji = "✅"
        elif avg_queue_wait <= 5:
            avg_wait_emoji = "⚠️"
        else:
            avg_wait_emoji = "❌"
        
        # Under 3 seconds %
        if under_3_pct >= 90:
            under_3_emoji = "✅"
        elif under_3_pct >= 70:
            under_3_emoji = "⚠️"
        else:
            under_3_emoji = "❌"
        
        # Over 12 seconds %
        if over_12_pct <= 2:
            over_12_emoji = "✅"
        elif over_12_pct <= 10:
            over_12_emoji = "⚠️"
        else:
            over_12_emoji = "❌"
        
        # Queue Drain
        if queue_drain_time is not None:
            if queue_drain_time <= 5:
                drain_emoji = "✅"
            elif queue_drain_time <= 15:
                drain_emoji = "⚠️"
            else:
                drain_emoji = "❌"
            drain_value = f"{queue_drain_time:.1f} seconds"
        else:
            drain_emoji = "✅"
            drain_value = "0.0 seconds"
        
        # Trend
        if abs(trend_per_minute) <= 0.1:
            trend_emoji = "✅"
        elif trend_per_minute <= 0.3:
            trend_emoji = "⚠️"
        else:
            trend_emoji = "❌"
        
        # Content Loss
        if content_loss_percent <= 2:
            loss_emoji = "✅"
        elif content_loss_percent <= 5:
            loss_emoji = "⚠️"
        else:
            loss_emoji = "❌"
        
        # Restart gaps average
        avg_gap = sum(g['gap_duration'] for g in self.restart_gaps) / len(self.restart_gaps) if self.restart_gaps else 0
        if avg_gap <= 5:
            gap_emoji = "✅"
        elif avg_gap <= 15:
            gap_emoji = "⚠️"
        else:
            gap_emoji = "❌"
        
        # Build Final Verdict
        issues = []
        if coverage_emoji == "❌":
            issues.append("Low coverage")
        if avg_wait_emoji == "❌":
            issues.append("High average wait")
        if under_3_emoji == "❌":
            issues.append("Low under-3-sec rate")
        if over_12_emoji == "❌":
            issues.append("High over-12-sec rate")
        if trend_emoji == "❌":
            issues.append("Queue building up")
        if loss_emoji == "❌":
            issues.append("High content loss")
        
        warnings = []
        if coverage_emoji == "⚠️":
            warnings.append("Coverage could improve")
        if avg_wait_emoji == "⚠️":
            warnings.append("Wait times slightly high")
        if under_3_emoji == "⚠️":
            warnings.append("Under-3-sec rate could improve")
        if over_12_emoji == "⚠️":
            warnings.append("Some slow segments")
        if trend_emoji == "⚠️":
            warnings.append("Queue trending up slightly")
        if loss_emoji == "⚠️":
            warnings.append("Moderate content loss")
        
        # Determine overall verdict
        if not issues and not warnings:
            verdict_emoji = "🎉"
            verdict_text = "PRODUCTION READY - All metrics excellent!"
        elif not issues and warnings:
            verdict_emoji = "👍"
            verdict_text = f"GOOD - Minor concerns: {', '.join(warnings)}"
        elif len(issues) <= 2:
            verdict_emoji = "⚠️"
            verdict_text = f"NEEDS ATTENTION - Issues: {', '.join(issues)}"
        else:
            verdict_emoji = "❌"
            verdict_text = f"NOT READY - Multiple issues: {', '.join(issues)}"
        
        # Get audio filename for display
        audio_filename = os.path.basename(self.audio_file_path) if self.audio_file_path else 'N/A (microphone)'
        
        # Build overview section
        overview_section = f"""
{'='*70}
                        QUICK OVERVIEW
{'='*70}
Audio File: {audio_filename}

KEY METRICS SUMMARY
-------------------
{duration_emoji} Duration:        {self.session.duration_seconds/60:.1f} minutes ({len(self.session.segments)} segments)
{coverage_emoji} Coverage:        {coverage_pct:.1f}% (target: >= 80%)
{avg_wait_emoji} Average Wait:    {avg_queue_wait:.2f} seconds (target: <= 2 sec)
{under_3_emoji} Under 3 sec:     {under_3_pct:.1f}% (target: >= 90%)
{over_12_emoji} Over 12 sec:     {over_12_pct:.1f}% (target: <= 2%)
{drain_emoji} Queue Drain:     {drain_value} (target: <= 5 sec)
{trend_emoji} Trend:           {trend_sign}{trend_per_minute:.2f} sec/min (target: stable)

CONTENT LOSS ANALYSIS
---------------------
{gap_emoji} Restart Gaps:    ~{words_lost_restarts} words ({len(self.restart_gaps)} restarts, {avg_gap:.1f}s avg gap)
   Skipped FINALs:  {words_lost_skipped} words ({self.skipped_finals_count} segments)
{loss_emoji} TOTAL LOST:      ~{total_words_lost} words ({content_loss_percent:.1f}% of expected)

FINAL VERDICT
-------------
{verdict_emoji} {verdict_text}

{'='*70}
"""
        
        summary = f"""
{'='*70}
TEST SUMMARY: {self.test_config['name']}
{'='*70}
{overview_section}
TEST CONFIGURATION
------------------
Mode: {self.test_mode} - {self.test_config['name']}
Description: {self.test_config['description']}
Audio Source: {self.audio_source}
Audio File: {os.path.basename(self.audio_file_path) if self.audio_file_path else 'N/A (microphone)'}
Duration Limit: {duration_limit_str}
Reading Speed: {self.test_config['reading_speed']} wpm
Min Display Time: {self.test_config['min_display_time']}s
Fade Duration: {self.test_config['fade_duration']}s
Chunk Splitting: {'Enabled (threshold: ' + str(chunk_threshold) + ' words)' if chunk_split_enabled else 'Disabled'}
Fast Recognition: {fast_recog_str}
Voice Activity Timeout: {voice_timeout_str}
Early Interim Display: {early_interim_str}
Context-Aware Translation: {'Enabled (using ' + str(self.test_config.get('context_chunks', 1)) + ' previous chunk(s))' if self.test_config.get('context_aware_translation') else 'Disabled'}
Translation Logging: {'Enabled' if self.test_config.get('save_translation_log') else 'Disabled'}
Glossary Lookup: {'Enabled (' + str(len(THEOLOGICAL_GLOSSARY)) + ' terms)' if self.test_config.get('use_glossary') else 'Disabled'}
Async Context Comparison: {'Enabled' if self.test_config.get('async_context_comparison') else 'Disabled'}
Hybrid Buffer: {'Enabled (max ' + str(self.test_config.get('buffer_max_words', 50)) + ' words, ' + str(self.test_config.get('buffer_timeout_seconds', 15)) + 's timeout)' if self.test_config.get('hybrid_buffer_enabled') else 'Disabled'}

STREAMING STATISTICS
--------------------
Time to First Result: {time_to_first_str}
Stream Restarts:      {self.stream_restart_count}
{restart_gap_section}
{self._get_hybrid_buffer_stats() if self.hybrid_buffer else ''}TIMING STATISTICS
-----------------
Test Duration: {self.session.duration_seconds/60:.1f} minutes
Active Time: {self.total_active_time/60:.1f} minutes

SEGMENT STATISTICS
------------------
Segments Processed: {len(self.session.segments)}
Segments Displayed: {self.display.segments_displayed}
Segments Skipped:   {self.display.segments_skipped}
Segments/Minute:    {segments_per_min:.1f}

SKIPPED CONTENT (Early Interim Mode)
------------------------------------
Skipped FINAL results: {self.skipped_finals_count} (had <= 2 new words)
Total words skipped:   {self.skipped_finals_words}

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
{chunk_section}{recognition_section}
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
        
        # Save translation log and run context comparison if enabled
        base_filename = summary_filename.replace('_summary.txt', '')
        
        if self.test_config.get('save_translation_log', False):
            print("\n📝 Saving translation log...")
            self._save_translation_log(base_filename)
            # Also generate native speaker review document
            print("\n👤 Generating native speaker review document...")
            self._save_native_speaker_review(base_filename)
        
        if self.test_config.get('run_context_comparison', False):
            print("\n🔍 Running context comparison diagnostic...")
            self._run_context_comparison(base_filename)
        
        # Mode 13: Save glossary corrections report
        if self.test_config.get('generate_glossary_report', False):
            print("\n📖 Saving glossary corrections report...")
            self._save_glossary_report(base_filename)
        
        # Mode 13: Save async context differences report
        if self.test_config.get('generate_difference_report', False):
            print("\n🔄 Saving context differences report...")
            self._save_context_differences_report(base_filename)
        
        # Stop async worker if running
        if hasattr(self, 'async_worker_running') and self.async_worker_running:
            self.async_worker_running = False
            if self.async_worker_thread:
                self.async_worker_thread.join(timeout=2.0)


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
        if config.get('force_faster_recognition') and not config.get('disable_enhanced'):
            print(f"     FAST RECOGNITION: API interim enabled")
        if config.get('disable_enhanced'):
            hints_status = "no hints" if config.get('disable_speech_context', True) else "hints ON"
            print(f"     MINIMAL LATENCY: default model, no enhanced, no punctuation, {hints_status}")
        if config.get('use_voice_activity_timeout'):
            print(f"     VOICE TIMEOUT: speech_end={config.get('speech_end_timeout_sec')}s (forces faster finalization)")
        if config.get('early_interim_display'):
            print(f"     EARLY INTERIM: Display after {config.get('early_interim_word_threshold')} words (don't wait for FINAL)")
        if config.get('hybrid_buffer_enabled'):
            print(f"     📦 HYBRID BUFFER: Sentence end OR {config.get('buffer_max_words')} words OR {config.get('buffer_timeout_seconds')}s timeout")
        if config.get('context_aware_translation'):
            print(f"     ⭐ CONTEXT TRANSLATION: Uses {config.get('context_chunks', 1)} previous segments for better quality")
        if config.get('use_glossary'):
            print(f"     GLOSSARY: {len(THEOLOGICAL_GLOSSARY)} theological terms for consistency")
        if config.get('async_context_comparison'):
            print(f"     ASYNC CONTEXT: Background comparison for quality analysis")
        if config.get('dual_stream_enabled'):
            print(f"     🔄 DUAL STREAMS: Overlapping streams for ~99% coverage (no restart gaps)")
    
    print("\n" + "-"*70)
    print("  L. View last test results")
    print("  C. Compare all test results")
    print("  Q. Quit")
    print("-"*70)
    
    while True:
        choice = input("\nEnter choice (0-17, L, C, Q): ").strip().upper()
        
        if choice == 'Q':
            print("Exiting...")
            exit(0)
        elif choice == 'L':
            view_last_results()
            return select_test_mode()  # Return to menu
        elif choice == 'C':
            compare_all_results()
            return select_test_mode()  # Return to menu
        elif choice in ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12', '13', '14', '15', '16', '17']:
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