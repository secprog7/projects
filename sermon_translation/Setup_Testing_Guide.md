# Complete Setup & Testing Guide for STT System with USB Audio Interface

## 🚀 Overview

This guide covers setting up and testing a complete Speech-to-Text and Translation system on your local machine with:
- Physical USB Audio Interface (Focusrite USB Audio)
- Live microphone input
- Real-time streaming transcription
- Real-time translation to Spanish
- Automatic file generation for review

---

## 📋 Step 1: Clone Repository to Local Machine

```bash
# Clone your repository
git clone <your-repo-url>
cd <your-repo-name>
```

---

## 🐍 Step 2: Set Up Python Environment

### 2.1 Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate it
# Windows (Command Prompt):
venv\Scripts\activate

# Windows (PowerShell):
venv\Scripts\Activate.ps1

# Mac/Linux:
source venv/bin/activate
```

You should see `(venv)` at the start of your terminal prompt.

### 2.2 Install Dependencies

```bash
pip install pyaudio google-cloud-speech google-cloud-translate numpy
```

**If PyAudio installation fails:**

**Windows:**
```bash
pip install pipwin
pipwin install pyaudio
```

**Mac:**
```bash
brew install portaudio
pip install pyaudio
```

**Linux:**
```bash
sudo apt-get install portaudio19-dev python3-pyaudio
pip install pyaudio
```

### 2.3 Create requirements.txt

Create `requirements.txt` in your project root:
```
pyaudio>=0.2.11
google-cloud-speech>=2.21.0
google-cloud-translate>=3.11.0
numpy>=1.24.0
```

---

## 🔌 Step 3: Connect & Verify USB Audio Interface

### 3.1 Connect Hardware
1. Plug in USB Audio Interface (Focusrite USB Audio) to your machine
2. Wait for drivers to install (Windows should auto-detect)
3. Verify it appears in your system audio devices

### 3.2 Test Audio Device Detection

Create `scripts/check_audio_devices.py`:

```python
import pyaudio

def list_audio_devices():
    """List all available audio input devices"""
    p = pyaudio.PyAudio()
    
    print("\n" + "="*60)
    print("📢 AVAILABLE AUDIO DEVICES")
    print("="*60 + "\n")
    
    usb_found = False
    
    for i in range(p.get_device_count()):
        info = p.get_device_info_by_index(i)
        
        # Check if it's an input device
        if info['maxInputChannels'] > 0:
            print(f"[{i}] {info['name']}")
            print(f"    Input Channels: {info['maxInputChannels']}")
            print(f"    Sample Rate: {int(info['defaultSampleRate'])} Hz")
            
            # Highlight USB devices
            if 'USB' in info['name'] or 'Focusrite' in info['name']:
                print(f"    ✅ USB AUDIO INTERFACE DETECTED!")
                usb_found = True
            print()
    
    p.terminate()
    
    if not usb_found:
        print("⚠️  USB Audio Interface not detected!")
        print("   Check that device is plugged in and drivers are installed.\n")
    else:
        print("✅ USB Audio Interface ready for testing!\n")

if __name__ == "__main__":
    list_audio_devices()
```

Run it:
```bash
python scripts/check_audio_devices.py
```

**Expected output:** You should see your Focusrite USB Audio Interface listed with a ✅

---

## 🔑 Step 4: Set Up Google Cloud Credentials

### 4.1 Download Service Account Key

1. Go to https://console.cloud.google.com
2. Select/Create your project
3. Enable APIs:
   - **Cloud Speech-to-Text API**
   - **Cloud Translation API**
4. Go to `IAM & Admin → Service Accounts`
5. Create service account with roles:
   - Cloud Speech Client
   - Cloud Translation API User
6. Click **Create Key** → Choose **JSON** → Download

### 4.2 Save Credentials Locally

1. Create a `credentials/` folder in your project
2. Save the JSON file as `credentials/your-key-name.json`
3. **Update `.gitignore`:**

```bash
# Add to .gitignore
credentials/
*.json
venv/
__pycache__/
results/*.txt
results/*.wav
```

### 4.3 Set Environment Variable

**Windows (PowerShell) - Each Session:**
```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS="credentials\your-key-name.json"
```

**Windows (Command Prompt) - Each Session:**
```cmd
set GOOGLE_APPLICATION_CREDENTIALS=credentials\your-key-name.json
```

**Mac/Linux:**
```bash
export GOOGLE_APPLICATION_CREDENTIALS="credentials/your-key-name.json"
```

**Verify it's set:**
```powershell
# PowerShell:
echo $env:GOOGLE_APPLICATION_CREDENTIALS

# Command Prompt:
echo %GOOGLE_APPLICATION_CREDENTIALS%
```

---

## 📁 Step 5: Organize Your Files

Your local project structure:

```
your-repo/
├── .gitignore
├── requirements.txt
├── README.md
├── credentials/
│   └── your-key-name.json          # Your credentials (NOT committed)
├── scripts/
│   ├── check_audio_devices.py       # Device checker
│   ├── check_audio_quality.py       # Audio quality analyzer
│   ├── usb_audio_stt_translate.py   # Main STT+Translation script
│   ├── streaming_recognize.py       # Streaming STT script
│   └── test_stt_live.py            # Testing suite
├── audio/
│   └── gold_standard_test.wav       # Test audio file
└── results/
    ├── live_translation_*.txt       # Live translation outputs
    ├── gold_standard_test_*.txt     # Test results
    └── latency_test_*.txt           # Latency measurements
```

---

## 📝 Step 6: Create All Required Scripts

### 6.1 Main Script: `scripts/usb_audio_stt_translate.py`

This is the updated version with real-time file saving:

```python
import pyaudio
import queue
import threading
from typing import Generator
from google.cloud import speech
from google.cloud import translate_v2 as translate
from datetime import datetime
import os

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


class SpeechToTextTranslator:
    """Handles Google Cloud Speech-to-Text and Translation with real-time file saving"""
    
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
        self.output_file = None
        
    def process_stream(self, audio_streamer, translate_enabled=True, save_to_file=True):
        """
        Process audio stream with STT and optional translation
        
        Args:
            audio_streamer: AudioStreamer instance
            translate_enabled: Whether to translate transcriptions
            save_to_file: Whether to save translations to a text file in real-time
        """
        # Create output file with timestamp
        if save_to_file:
            os.makedirs("results", exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"results/live_translation_{timestamp}.txt"
            self.output_file = open(output_filename, 'w', encoding='utf-8')
            
            # Write header
            self.output_file.write("LIVE TRANSLATION SESSION\n")
            self.output_file.write("="*60 + "\n")
            self.output_file.write(f"Date: {datetime.now()}\n")
            self.output_file.write(f"Source Language: {self.source_language}\n")
            self.output_file.write(f"Target Language: {self.target_language}\n")
            self.output_file.write("="*60 + "\n\n")
            self.output_file.flush()
            
            print(f"\n💾 Saving translations to: {output_filename}\n")
        
        # Configure STT
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=self.source_language,
            enable_automatic_punctuation=True,
            model="default",
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
        if translate_enabled:
            print(f"🌐 Translating to {self.target_language}...\n")
        
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
                        
                        # Final transcription
                        print(f"📝 [{timestamp_str}] Original: {transcript}")
                        
                        # Translate if enabled
                        if translate_enabled:
                            translation = self.translate_text(transcript)
                            print(f"🌍 [{timestamp_str}] Translated: {translation}")
                            
                            # Save to file in real-time
                            if self.output_file:
                                self.output_file.write(f"[{timestamp_str}] Segment {segment_count}\n")
                                self.output_file.write(f"Original ({self.source_language}): {transcript}\n")
                                self.output_file.write(f"Translation ({self.target_language}): {translation}\n")
                                self.output_file.write("-" * 60 + "\n\n")
                                self.output_file.flush()  # Write immediately
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
                self.output_file.close()
                print(f"\n✅ Translation saved to: {output_filename}")
    
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
                source_language=self.source_language.split('-')[0]
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
        # save_to_file=True will create a timestamped file in results/
        translator.process_stream(
            streamer, 
            translate_enabled=ENABLE_TRANSLATION,
            save_to_file=True
        )
        
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping...")
    finally:
        streamer.stop_stream()
        print("\n✅ Done!")
```

### 6.2 Audio Quality Checker: `scripts/check_audio_quality.py`

```python
import wave
import numpy as np

def analyze_audio_file(audio_file):
    """Analyze audio file quality and parameters"""
    print("\n" + "="*60)
    print("🔍 AUDIO QUALITY ANALYSIS")
    print("="*60 + "\n")
    
    with wave.open(audio_file, 'rb') as wf:
        # Get parameters
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        duration = n_frames / sample_rate
        
        # Read audio data
        audio_data = wf.readframes(n_frames)
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        
        # Calculate metrics
        max_amplitude = np.max(np.abs(audio_array))
        avg_amplitude = np.mean(np.abs(audio_array))
        max_possible = 32767  # 16-bit max
        
        print(f"📊 BASIC PARAMETERS:")
        print(f"   File: {audio_file}")
        print(f"   Duration: {duration:.2f} seconds ({duration/60:.2f} minutes)")
        print(f"   Sample Rate: {sample_rate} Hz")
        print(f"   Channels: {channels} ({'Mono' if channels == 1 else 'Stereo'})")
        print(f"   Bit Depth: {sample_width * 8}-bit")
        
        print(f"\n🔊 AUDIO LEVELS:")
        print(f"   Max Amplitude: {max_amplitude} / {max_possible} ({max_amplitude/max_possible*100:.1f}%)")
        print(f"   Average Amplitude: {avg_amplitude:.0f}")
        
        # Quality checks
        print(f"\n✅ QUALITY CHECKS:")
        
        if sample_rate >= 16000:
            print(f"   ✅ Sample rate good ({sample_rate}Hz)")
        else:
            print(f"   ⚠️  Sample rate low ({sample_rate}Hz) - recommend 16kHz+")
        
        if channels == 1:
            print(f"   ✅ Mono audio (optimal for speech)")
        else:
            print(f"   ⚠️  Stereo audio - consider converting to mono")
        
        if max_amplitude < max_possible * 0.3:
            print(f"   ⚠️  Audio quiet - consider boosting volume")
        elif max_amplitude > max_possible * 0.95:
            print(f"   ⚠️  Audio may be clipping - too loud!")
        else:
            print(f"   ✅ Audio levels good")
        
        print("\n" + "="*60 + "\n")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
    else:
        audio_file = input("Enter path to audio file: ").strip()
    
    try:
        analyze_audio_file(audio_file)
    except FileNotFoundError:
        print(f"❌ Error: File '{audio_file}' not found")
    except Exception as e:
        print(f"❌ Error analyzing file: {e}")
```

---

## ▶️ Step 7: Run Your Tests

Make sure your USB Audio Interface is connected and credentials are set!

### Test 1: Verify Audio Device
```bash
python scripts/check_audio_devices.py
```

### Test 2: Check Audio Quality (for file tests)
```bash
python scripts/check_audio_quality.py audio/gold_standard_test.wav
```

### Test 3: Gold Standard File Test
```bash
python scripts/test_stt_live.py
# Choose: 3
# Enter: audio/gold_standard_test.wav
# Enter the actual spoken text
```

### Test 4: Live Latency Test
```bash
python scripts/test_stt_live.py
# Choose: 2
# Perform 5 trials with stopwatch
```

### Test 5: Full System (Live STT + Translation with File Output)
```bash
python scripts/test_stt_live.py
# Choose: 4
# Speak into microphone
# Translation saved to results/live_translation_*.txt
```

### Test 6: Gold Standard Translation Test
```bash
python scripts/test_stt_live.py
# Choose: 5
# Enter: audio/gold_standard_test.wav
# Enter expected English and Spanish texts
```

---

## 📊 Understanding the Output Files

### Live Translation File (`results/live_translation_TIMESTAMP.txt`)

```
LIVE TRANSLATION SESSION
============================================================
Date: 2024-10-18 14:30:52
Source Language: en-US
Target Language: es
============================================================

[14:31:05] Segment 1
Original (en-US): Good morning everyone.
Translation (es): Buenos días a todos.
------------------------------------------------------------

[14:31:12] Segment 2
Original (en-US): Let us pray.
Translation (es): Oremos.
------------------------------------------------------------

============================================================
Session ended: 2024-10-18 15:15:30
Total segments: 47
```

**Features:**
- ✅ Real-time writing (file updates as speech is transcribed)
- ✅ Timestamps for each segment
- ✅ Both original and translated text
- ✅ Session summary at end
- ✅ Can be opened during live session for review

### Gold Standard Test Results

Contains:
- Transcription vs expected text
- Confidence scores (average, min, max, individual)
- Processing time
- Accuracy assessment

---

## 🎯 Complete Testing Workflow

### For Live Preaching/Sermon:

1. **Setup (one time per session)**
   ```bash
   # Activate venv
   venv\Scripts\activate
   
   # Set credentials
   $env:GOOGLE_APPLICATION_CREDENTIALS="credentials\your-key-name.json"
   
   # Verify USB device
   python scripts/check_audio_devices.py
   ```

2. **Start Live Translation**
   ```bash
   python scripts/test_stt_live.py
   # Choose: 4
   ```

3. **During Session**
   - Speak into microphone
   - Watch screen for real-time translations
   - File is being saved automatically to `results/`

4. **After Session**
   - Press `Ctrl+C` to stop
   - Open the results file
   - Share with reviewer

5. **Review & Document**
   - Check translation quality
   - Note any issues
   - Save feedback for improvements

---

## 🔧 Troubleshooting

### USB Device Not Detected
```bash
python scripts/check_audio_devices.py
```
Check Windows Device Manager or system sound settings.

### Google Cloud Authentication Error
```powershell
# Verify credentials path
echo $env:GOOGLE_APPLICATION_CREDENTIALS

# Test authentication
python -c "from google.cloud import speech; client = speech.SpeechClient(); print('✅ Auth successful!')"
```

### PyAudio Errors
```bash
pip install pipwin
pipwin install pyaudio
```

### Poor Transcription Accuracy
1. Run audio quality checker
2. Check microphone distance (6-12 inches optimal)
3. Reduce background noise
4. Consider using enhanced model: `model="latest_long"`

### File Too Large Error (>10MB)
The streaming method automatically handles this, but if issues persist:
```bash
# Pre-process audio to reduce size
ffmpeg -i input.wav -ar 16000 -ac 1 output.wav
```

---

## ✅ Testing Checklist

- [ ] Repository cloned to local machine
- [ ] Virtual environment created and activated
- [ ] All dependencies installed
- [ ] USB Audio Interface connected and detected
- [ ] Google Cloud credentials configured
- [ ] `.gitignore` includes credentials folder
- [ ] Audio device detection test passed
- [ ] Audio quality check completed (for file tests)
- [ ] Gold standard file test completed
- [ ] Live latency test completed
- [ ] Live translation test completed
- [ ] Translation file generated and reviewed
- [ ] Results documented
- [ ] Changes committed to GitHub (without credentials!)

---

## 📤 Committing Your Work

```bash
# Make sure credentials are NOT included
git status

# Should NOT show credentials/ folder or .json files
# If it does, update .gitignore

# Stage files
git add scripts/ results/ audio/ .gitignore requirements.txt

# Commit
git commit -m "Add complete STT and translation system with real-time file output"

# Push
git push origin main
```

---

## 🎯 Quick Reference Commands

```bash
# Activate environment
venv\Scripts\activate

# Set credentials (do this each session)
$env:GOOGLE_APPLICATION_CREDENTIALS="credentials\your-key-name.json"

# Check USB device
python scripts/check_audio_devices.py

# Run live translation (most common use)
python scripts/test_stt_live.py
# Choose: 4

# Test with audio file
python scripts/test_stt_live.py
# Choose: 3 or 5
```

---

## 💡 Tips for Best Results

1. **Microphone Setup**
   - Position 6-12 inches from speaker
   - Use pop filter if available
   - Minimize background noise

2. **Audio Quality**
   - Test audio levels before starting
   - Speak clearly and at moderate pace
   - Avoid multiple people speaking simultaneously

3. **Translation Review**
   - Have reviewer check file during or after session
   - Note any recurring mistranslations
   - Add common terms to speech context for improvements

4. **Session Management**
   - Start recording before speaking begins
   - Let each sentence complete before next
   - Stop cleanly with Ctrl+C when done

---

## 📚 Additional Resources

- Google Cloud Speech-to-Text: https://cloud.google.com/speech-to-text/docs
- Google Cloud Translate: https://cloud.google.com/translate/docs
- PyAudio Documentation: https://people.csail.mit.edu/hubert/pyaudio/docs/

---

## 🎉 You're All Set!

You now have a complete real-time speech-to-text and translation system that:
- ✅ Captures live audio from USB interface
- ✅ Transcribes speech to text
- ✅ Translates to Spanish in real-time
- ✅ Saves everything to a file for review
- ✅ Provides detailed test results and metrics

Happy translating! 🎤→📝→🌐