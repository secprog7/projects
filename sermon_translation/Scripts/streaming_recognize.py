from google.cloud import speech
import pyaudio
import queue
import threading

# Audio configuration for optimal streaming
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms chunks
FORMAT = pyaudio.paInt16
CHANNELS = 1

class StreamingTranscriber:
    """Uses Google's StreamingRecognize to convert audio chunks to English text"""
    
    def __init__(self, device_index=None):
        self.client = speech.SpeechClient()
        self.audio_interface = pyaudio.PyAudio()
        self.device_index = device_index
        self.audio_queue = queue.Queue()
        self.is_streaming = False
        
    def _audio_generator(self):
        """Generator that yields audio chunks from the queue"""
        while self.is_streaming:
            chunk = self.audio_queue.get()
            if chunk is None:
                return
            yield chunk
    
    def _fill_buffer(self, stream):
        """Thread function to continuously fill audio buffer"""
        while self.is_streaming:
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                self.audio_queue.put(data)
            except Exception as e:
                print(f"Audio read error: {e}")
                break
    
    def transcribe_stream(self, language_code="en-US", single_utterance=False):
        """
        Stream audio chunks to Google's StreamingRecognize method
        
        Args:
            language_code: Language for transcription (default: "en-US")
            single_utterance: If True, stops after first complete utterance
        """
        # Configure recognition settings
        recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=language_code,
            enable_automatic_punctuation=True,
            model="command_and_search",  # Optimized for short queries
            use_enhanced=True,  # Use enhanced model if available
        )
        
        # Configure streaming settings
        streaming_config = speech.StreamingRecognitionConfig(
            config=recognition_config,
            interim_results=True,  # Get partial results
            single_utterance=single_utterance
        )
        
        # Open audio stream
        audio_stream = self.audio_interface.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=CHUNK
        )
        
        print(f"🎤 Streaming audio to Google Cloud Speech-to-Text...")
        print(f"📝 Language: {language_code}")
        print(f"🎧 Listening...\n")
        
        self.is_streaming = True
        
        # Start thread to fill audio buffer
        audio_thread = threading.Thread(
            target=self._fill_buffer, 
            args=(audio_stream,)
        )
        audio_thread.start()
        
        try:
            # Create request generator for StreamingRecognize
            def request_generator():
                for content in self._audio_generator():
                    yield speech.StreamingRecognizeRequest(audio_content=content)
            
            # Call Google's StreamingRecognize method
            responses = self.client.streaming_recognize(
                streaming_config,
                request_generator()
            )
            
            # Process streaming responses
            self._process_responses(responses)
            
        except Exception as e:
            print(f"\n❌ Error during streaming: {e}")
        finally:
            self.is_streaming = False
            audio_thread.join()
            audio_stream.stop_stream()
            audio_stream.close()
            self.audio_interface.terminate()
    
    def _process_responses(self, responses):
        """
        Process StreamingRecognize responses and extract English text
        
        Args:
            responses: Iterator of StreamingRecognizeResponse objects
        """
        num_chars_printed = 0
        
        for response in responses:
            if not response.results:
                continue
            
            # The results list contains consecutive results corresponding to
            # consecutive portions of the audio
            result = response.results[0]
            if not result.alternatives:
                continue
            
            # Extract the transcript (English text)
            transcript = result.alternatives[0].transcript
            
            # Display interim results (overwrite previous line)
            if not result.is_final:
                # Clear previous interim result
                print('\r' + ' ' * num_chars_printed, end='', flush=True)
                print(f'\r💭 {transcript}', end='', flush=True)
                num_chars_printed = len(transcript) + 3
            else:
                # Final result - print on new line
                print('\r' + ' ' * num_chars_printed, end='', flush=True)
                print(f'\r✅ {transcript}')
                
                # Get confidence score if available
                confidence = result.alternatives[0].confidence
                if confidence > 0:
                    print(f'   Confidence: {confidence:.2%}')
                
                print('-' * 60)
                num_chars_printed = 0


class ChunkedAudioTranscriber:
    """Alternative approach: manually chunk audio and transcribe"""
    
    def __init__(self):
        self.client = speech.SpeechClient()
    
    def transcribe_audio_chunks(self, audio_chunks, language_code="en-US"):
        """
        Convert a list of audio chunks to English text using StreamingRecognize
        
        Args:
            audio_chunks: List of audio data chunks (bytes)
            language_code: Language code (default: "en-US")
            
        Returns:
            List of transcription results
        """
        # Configure recognition
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=language_code,
            enable_automatic_punctuation=True,
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=False
        )
        
        # Create requests from chunks
        def requests():
            for chunk in audio_chunks:
                yield speech.StreamingRecognizeRequest(audio_content=chunk)
        
        # Call StreamingRecognize
        responses = self.client.streaming_recognize(streaming_config, requests())
        
        # Collect transcriptions
        transcriptions = []
        for response in responses:
            for result in response.results:
                if result.is_final:
                    transcriptions.append(result.alternatives[0].transcript)
        
        return transcriptions


# Usage Example 1: Real-time streaming from microphone
def main_realtime():
    transcriber = StreamingTranscriber()
    
    try:
        transcriber.transcribe_stream(
            language_code="en-US",
            single_utterance=False  # Continuous listening
        )
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopped by user")


# Usage Example 2: Process pre-recorded audio chunks
def main_chunks():
    import wave
    
    # Read audio file and split into chunks
    with wave.open('audio.wav', 'rb') as wf:
        audio_data = wf.readframes(wf.getnframes())
        
        # Split into chunks
        chunk_size = CHUNK * 2  # 2 bytes per sample (16-bit)
        chunks = [audio_data[i:i+chunk_size] 
                  for i in range(0, len(audio_data), chunk_size)]
    
    # Transcribe chunks
    transcriber = ChunkedAudioTranscriber()
    results = transcriber.transcribe_audio_chunks(chunks, language_code="en-US")
    
    print("📝 Transcription Results:")
    for i, text in enumerate(results, 1):
        print(f"{i}. {text}")


if __name__ == "__main__":
    # Choose which example to run:
    
    # Option 1: Real-time streaming transcription
    main_realtime()
    
    # Option 2: Process audio chunks
    # main_chunks()