from google.cloud import speech
import os

# Force set credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials/google-key-new.json'

def test_streaming():
    """Test if streaming authentication works"""
    print("Testing streaming authentication...")
    
    client = speech.SpeechClient()
    
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="en-US",
    )
    
    streaming_config = speech.StreamingRecognitionConfig(
        config=config,
        interim_results=False
    )
    
    # Create a dummy request
    def request_generator():
        # Send empty audio just to test authentication
        yield speech.StreamingRecognizeRequest(audio_content=b'\x00' * 1024)
    
    try:
        responses = client.streaming_recognize(streaming_config, request_generator())
        for response in responses:
            print("✅ Streaming authentication successful!")
            break
    except Exception as e:
        print(f"❌ Streaming authentication failed: {e}")

if __name__ == "__main__":
    test_streaming()