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