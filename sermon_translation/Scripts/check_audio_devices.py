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
            if 'USB' in info['name'] or '0.2.C' in info['name']:
                print(f"    ✅ USB AUDIO INTERFACE DETECTED!")
                usb_found = True
            print()
    
    p.terminate()
    
    if not usb_found:
        print("⚠️  USB Audio Interface (0.2.C) not detected!")
        print("   Check that device is plugged in and drivers are installed.\n")
    else:
        print("✅ USB Audio Interface ready for testing!\n")

if __name__ == "__main__":
    list_audio_devices()