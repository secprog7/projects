import time
from datetime import datetime
from streaming_recognize import StreamingTranscriber
import os

class LiveSTTTester:
    """Test STT with live USB microphone input"""
    
    def __init__(self):
        self.results = []
        
    def test_accuracy_live(self, device_index=None):
        """
        Test STT accuracy with live speech
        Speak the gold standard text and compare
        """
        print("\n" + "="*60)
        print("🧪 STT ACCURACY TEST - LIVE INPUT")
        print("="*60)
        
        print("\n📋 INSTRUCTIONS:")
        print("1. You will speak the gold standard text")
        print("2. The system will transcribe it in real-time")
        print("3. Compare transcription with expected text")
        print("4. Note any errors\n")
        
        expected = input("Enter the gold standard text you will speak:\n> ")
        input("\nPress Enter when ready to speak...")
        
        print("\n🎤 LISTENING... Speak now!")
        print("Press Ctrl+C when finished speaking.\n")
        
        transcriber = StreamingTranscriber(device_index=device_index)
        
        try:
            transcriber.transcribe_stream(language_code="en-US")
        except KeyboardInterrupt:
            print("\n\n✅ Transcription stopped.\n")
        
        # Manual comparison
        print("\n" + "="*60)
        print("📝 MANUAL ACCURACY CHECK")
        print("="*60)
        print(f"\nExpected: {expected}")
        print("\nPlease compare with the transcription above.")
        
        accuracy = input("\nRate accuracy (1-5, 5=perfect): ")
        notes = input("Notes on errors or issues: ")
        
        self._save_accuracy_results(expected, accuracy, notes)
    
    def test_latency_live(self, device_index=None, num_trials=5):
        """
        Test STT latency with live input
        Measures time from end of speech to transcription
        """
        print("\n" + "="*60)
        print("⏱️  STT LATENCY TEST - LIVE INPUT")
        print("="*60)
        
        print(f"\n📋 INSTRUCTIONS:")
        print(f"You will perform {num_trials} trials.")
        print("For each trial:")
        print("  1. Speak a clear sentence")
        print("  2. START stopwatch when you FINISH speaking")
        print("  3. STOP stopwatch when transcription appears")
        print("  4. Record the time\n")
        
        latencies = []
        
        for trial in range(1, num_trials + 1):
            print(f"\n{'='*60}")
            print(f"TRIAL {trial}/{num_trials}")
            print("="*60)
            
            input("Press Enter when ready to speak...")
            
            print("\n🎤 Speak now, then start your stopwatch when done!")
            print("Press Ctrl+C after you see the transcription.\n")
            
            transcriber = StreamingTranscriber(device_index=device_index)
            
            try:
                transcriber.transcribe_stream(
                    language_code="en-US",
                    single_utterance=True
                )
            except KeyboardInterrupt:
                pass
            
            latency = input(f"\n⏱️  Enter latency for trial {trial} (seconds): ")
            
            try:
                latency_float = float(latency)
                latencies.append(latency_float)
                print(f"✅ Recorded: {latency_float}s")
            except ValueError:
                print("⚠️  Invalid input, skipping this trial")
        
        # Calculate statistics
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            min_latency = min(latencies)
            max_latency = max(latencies)
            
            print("\n" + "="*60)
            print("📊 LATENCY TEST RESULTS")
            print("="*60)
            print(f"\nTrials completed: {len(latencies)}")
            print(f"Average latency: {avg_latency:.2f}s")
            print(f"Min latency: {min_latency:.2f}s")
            print(f"Max latency: {max_latency:.2f}s")
            
            # Assessment
            if avg_latency < 1.0:
                assessment = "Excellent (< 1s)"
            elif avg_latency < 2.0:
                assessment = "Good (1-2s)"
            elif avg_latency < 3.0:
                assessment = "Acceptable (2-3s)"
            else:
                assessment = "Needs improvement (> 3s)"
            
            print(f"\nAssessment: {assessment}\n")
            
            self._save_latency_results(latencies, avg_latency, assessment)
        else:
            print("\n⚠️  No valid latency measurements recorded.")
    
    def test_gold_standard_file(self, audio_file):
        """Test with pre-recorded gold standard audio file"""
        from google.cloud import speech
        import wave
        
        print("\n" + "="*60)
        print("🧪 GOLD STANDARD FILE TEST")
        print("="*60)
        
        print(f"\nAudio file: {audio_file}\n")
        
        # Read file info
        with wave.open(audio_file, 'rb') as wf:
            sample_rate = wf.getframerate()
            file_size = os.path.getsize(audio_file)
        
        print(f"📊 File size: {file_size / 1024 / 1024:.2f} MB")
        
        client = speech.SpeechClient()
        
        # Use streaming for large files (>10MB) or files longer than 1 minute
        if file_size > 10 * 1024 * 1024:  # 10MB
            print("⚠️  Large file detected - using streaming method...")
            transcription, processing_time, confidence_scores = self._transcribe_file_streaming(audio_file, sample_rate, client)
        else:
            print("⏳ Transcribing with standard method...")
            transcription, processing_time, confidence_scores = self._transcribe_file_standard(audio_file, sample_rate, client)
        
        # Calculate average confidence
        if confidence_scores:
            avg_confidence = sum(confidence_scores) / len(confidence_scores)
            min_confidence = min(confidence_scores)
            max_confidence = max(confidence_scores)
        else:
            avg_confidence = 0
            min_confidence = 0
            max_confidence = 0
        
        end_time = processing_time
        
        print(f"\n📝 TRANSCRIPTION:")
        print(f"{transcription}\n")
        
        print(f"⏱️  Processing time: {processing_time:.2f}s")
        
        # Display confidence scores
        print(f"\n📊 CONFIDENCE SCORES:")
        if confidence_scores:
            print(f"   Average: {avg_confidence:.2%}")
            print(f"   Range: {min_confidence:.2%} - {max_confidence:.2%}")
            print(f"   Segments: {len(confidence_scores)}")
        else:
            print("   No confidence scores available")
        
        print()
        
        expected = input("Enter the actual spoken text from the audio: ")
        
        print("\n" + "="*60)
        print("COMPARISON")
        print("="*60)
        print(f"Expected: {expected}")
        print(f"Got:      {transcription}\n")
        
        if expected.lower().strip() == transcription.lower().strip():
            print("✅ Perfect match!")
        else:
            print("⚠️  Differences detected")
        
        self._save_file_results(audio_file, transcription, expected, processing_time, 
                                avg_confidence, confidence_scores)
    
    def _transcribe_file_standard(self, audio_file, sample_rate, client):
        """Transcribe using standard recognize method (for files < 10MB)"""
        from google.cloud import speech
        import wave
        
        with wave.open(audio_file, 'rb') as wf:
            audio_content = wf.readframes(wf.getnframes())
        
        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code="en-US",
            enable_automatic_punctuation=True,
        )
        
        start_time = time.time()
        response = client.recognize(config=config, audio=audio)
        processing_time = time.time() - start_time
        
        transcription = ""
        confidence_scores = []
        
        for result in response.results:
            transcription += result.alternatives[0].transcript + " "
            confidence_scores.append(result.alternatives[0].confidence)
        
        return transcription.strip(), processing_time, confidence_scores
    
    def test_gold_standard_translation(self, audio_file, target_language="es"):
        """
        Complete pipeline test: English audio → Transcription → Spanish Translation
        Tests the full STT + Translation workflow with gold standard file
        """
        from google.cloud import speech, translate_v2 as translate
        import wave
        
        print("\n" + "="*60)
        print("🌐 GOLD STANDARD: ENGLISH AUDIO → SPANISH TRANSLATION")
        print("="*60)
        
        print(f"\nAudio file: {audio_file}")
        print(f"Target language: {target_language}\n")
        
        # Read file info
        with wave.open(audio_file, 'rb') as wf:
            sample_rate = wf.getframerate()
            file_size = os.path.getsize(audio_file)
        
        print(f"📊 File size: {file_size / 1024 / 1024:.2f} MB\n")
        
        # Step 1: Transcribe English audio
        print("=" * 60)
        print("STEP 1: TRANSCRIBING ENGLISH AUDIO")
        print("=" * 60 + "\n")
        
        client = speech.SpeechClient()
        
        if file_size > 10 * 1024 * 1024:
            print("⚠️  Large file detected - using streaming method...")
            transcription, stt_time = self._transcribe_file_streaming(audio_file, sample_rate, client)
        else:
            print("⏳ Transcribing...")
            transcription, stt_time = self._transcribe_file_standard(audio_file, sample_rate, client)
        
        print(f"\n✅ Transcription complete in {stt_time:.2f}s\n")
        print(f"📝 ENGLISH TRANSCRIPTION:")
        print(f"{transcription}\n")
        
        # Step 2: Translate to Spanish
        print("=" * 60)
        print("STEP 2: TRANSLATING TO SPANISH")
        print("=" * 60 + "\n")
        
        translate_client = translate.Client()
        
        print("⏳ Translating...")
        start_time = time.time()
        
        translation_result = translate_client.translate(
            transcription,
            target_language=target_language,
            source_language="en"
        )
        
        translation_time = time.time() - start_time
        spanish_text = translation_result['translatedText']
        
        print(f"\n✅ Translation complete in {translation_time:.2f}s\n")
        print(f"🌍 SPANISH TRANSLATION:")
        print(f"{spanish_text}\n")
        
        # Summary
        total_time = stt_time + translation_time
        
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"\n⏱️  Total processing time: {total_time:.2f}s")
        print(f"   - STT time: {stt_time:.2f}s")
        print(f"   - Translation time: {translation_time:.2f}s\n")
        
        # Get expected texts for comparison
        print("=" * 60)
        print("ACCURACY VERIFICATION")
        print("=" * 60 + "\n")
        
        expected_english = input("Enter the actual English text spoken in the audio:\n> ").strip()
        expected_spanish = input("\nEnter the expected Spanish translation:\n> ").strip()
        
        # Compare English transcription
        print("\n📋 ENGLISH TRANSCRIPTION COMPARISON:")
        print(f"Expected: {expected_english}")
        print(f"Got:      {transcription}")
        
        if expected_english.lower() == transcription.lower():
            print("✅ Perfect transcription match!")
            transcription_quality = "Perfect"
        else:
            print("⚠️  Transcription differences detected")
            transcription_quality = "Needs review"
        
        # Compare Spanish translation
        print("\n📋 SPANISH TRANSLATION COMPARISON:")
        print(f"Expected: {expected_spanish}")
        print(f"Got:      {spanish_text}")
        
        if expected_spanish.lower() == spanish_text.lower():
            print("✅ Perfect translation match!")
            translation_quality = "Perfect"
        else:
            print("⚠️  Translation differences detected")
            translation_quality = "Needs review"
        
        # Save comprehensive results
        self._save_translation_results(
            audio_file,
            transcription,
            spanish_text,
            expected_english,
            expected_spanish,
            stt_time,
            translation_time,
            transcription_quality,
            translation_quality
        )
        
        print("\n✅ Test complete!")
        
        return transcription, spanish_text
    
    def _save_translation_results(self, audio_file, transcription, translation, 
                                   expected_english, expected_spanish, stt_time, 
                                   translation_time, transcription_quality, translation_quality):
        """Save gold standard translation test results"""
        os.makedirs("results", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        filename = f"results/translation_test_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("GOLD STANDARD TRANSLATION TEST\n")
            f.write("English Audio → Transcription → Spanish Translation\n")
            f.write("="*60 + "\n")
            f.write(f"Date: {datetime.now()}\n")
            f.write(f"Audio file: {audio_file}\n\n")
            
            f.write("PROCESSING TIMES:\n")
            f.write(f"  STT Time: {stt_time:.2f}s\n")
            f.write(f"  Translation Time: {translation_time:.2f}s\n")
            f.write(f"  Total Time: {stt_time + translation_time:.2f}s\n\n")
            
            f.write("="*60 + "\n")
            f.write("ENGLISH TRANSCRIPTION\n")
            f.write("="*60 + "\n")
            f.write(f"Expected:\n{expected_english}\n\n")
            f.write(f"Transcribed:\n{transcription}\n\n")
            f.write(f"Quality: {transcription_quality}\n\n")
            
            f.write("="*60 + "\n")
            f.write("SPANISH TRANSLATION\n")
            f.write("="*60 + "\n")
            f.write(f"Expected:\n{expected_spanish}\n\n")
            f.write(f"Translated:\n{translation}\n\n")
            f.write(f"Quality: {translation_quality}\n\n")
        
        print(f"\n💾 Results saved to: {filename}")
    
    def _transcribe_file_streaming(self, audio_file, sample_rate, client):
        """Transcribe using streaming method (for large files)"""
        from google.cloud import speech
        import wave
        
        config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code="en-US",
            enable_automatic_punctuation=True,
        )
        
        streaming_config = speech.StreamingRecognitionConfig(
            config=config,
            interim_results=False
        )
        
        # Read audio in chunks
        def audio_generator():
            with wave.open(audio_file, 'rb') as wf:
                chunk_size = 1024
                while True:
                    data = wf.readframes(chunk_size)
                    if not data:
                        break
                    yield speech.StreamingRecognizeRequest(audio_content=data)
        
        start_time = time.time()
        responses = client.streaming_recognize(streaming_config, audio_generator())
        
        transcription = ""
        confidence_scores = []
        
        for response in responses:
            for result in response.results:
                if result.is_final:
                    transcription += result.alternatives[0].transcript + " "
                    confidence_scores.append(result.alternatives[0].confidence)
        
        processing_time = time.time() - start_time
        
        return transcription.strip(), processing_time, confidence_scores
    
    def _save_accuracy_results(self, expected, accuracy, notes):
        """Save accuracy test results"""
        os.makedirs("results", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        with open(f"results/accuracy_test_{timestamp}.txt", 'w') as f:
            f.write("STT ACCURACY TEST - LIVE INPUT\n")
            f.write("="*60 + "\n")
            f.write(f"Date: {datetime.now()}\n\n")
            f.write(f"EXPECTED TEXT:\n{expected}\n\n")
            f.write(f"ACCURACY RATING: {accuracy}/5\n\n")
            f.write(f"NOTES:\n{notes}\n")
        
        print(f"\n💾 Results saved to: results/accuracy_test_{timestamp}.txt")
    
    def _save_latency_results(self, latencies, avg, assessment):
        """Save latency test results"""
        os.makedirs("results", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        with open(f"results/latency_test_{timestamp}.txt", 'w') as f:
            f.write("STT LATENCY TEST - LIVE INPUT\n")
            f.write("="*60 + "\n")
            f.write(f"Date: {datetime.now()}\n\n")
            f.write(f"Number of trials: {len(latencies)}\n\n")
            f.write("INDIVIDUAL MEASUREMENTS:\n")
            for i, lat in enumerate(latencies, 1):
                f.write(f"  Trial {i}: {lat:.2f}s\n")
            f.write(f"\nAVERAGE LATENCY: {avg:.2f}s\n")
            f.write(f"ASSESSMENT: {assessment}\n")
        
        print(f"\n💾 Results saved to: results/latency_test_{timestamp}.txt")
    
    def _save_file_results(self, audio_file, transcription, expected, processing_time,
                           avg_confidence, confidence_scores):
        """Save gold standard file test results"""
        os.makedirs("results", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        filename = f"results/gold_standard_test_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("GOLD STANDARD FILE TEST\n")
            f.write("="*60 + "\n")
            f.write(f"Date: {datetime.now()}\n")
            f.write(f"Audio file: {audio_file}\n")
            f.write(f"Processing time: {processing_time:.2f}s\n\n")
            
            f.write("CONFIDENCE SCORES:\n")
            if confidence_scores:
                f.write(f"  Average Confidence: {avg_confidence:.2%}\n")
                f.write(f"  Min Confidence: {min(confidence_scores):.2%}\n")
                f.write(f"  Max Confidence: {max(confidence_scores):.2%}\n")
                f.write(f"  Number of Segments: {len(confidence_scores)}\n")
                f.write(f"  Individual Scores: ")
                for i, score in enumerate(confidence_scores):
                    f.write(f"{score:.2%}")
                    if i < len(confidence_scores) - 1:
                        f.write(", ")
                f.write("\n")
            else:
                f.write(f"  Average Confidence: {avg_confidence:.2%}\n")
                f.write("  No individual confidence scores available\n")
            f.write("\n")
            
            f.write(f"EXPECTED:\n{expected}\n\n")
            f.write(f"TRANSCRIPTION:\n{transcription}\n")
        
        print(f"\n💾 Results saved to: {filename}")


if __name__ == "__main__":
    print("\n🎯 STT TESTING SUITE")
    print("="*60)
    print("\nSelect test:")
    print("1. Accuracy Test (speak live)")
    print("2. Latency Test (speak live, measure timing)")
    print("3. Gold Standard File Test (0.2.D)")
    print("4. Full System Test (with translation)")
    print("5. Gold Standard File → Spanish Translation Test")
    
    choice = input("\nChoice (1-5): ").strip()
    
    tester = LiveSTTTester()
    
    if choice == "1":
        tester.test_accuracy_live()
        
    elif choice == "2":
        trials = input("Number of trials (default 5): ").strip()
        trials = int(trials) if trials else 5
        tester.test_latency_live(num_trials=trials)
        
    elif choice == "3":
        audio_path = input("Path to audio file: ").strip()
        tester.test_gold_standard_file(audio_path)
        
    elif choice == "4":
        print("\n🌐 Running full system with translation...")
        from usb_audio_stt_translate import AudioStreamer, SpeechToTextTranslator
        
        streamer = AudioStreamer()
        translator = SpeechToTextTranslator(
            source_language="en-US",
            target_language="es"
        )
        
        try:
            streamer.start_stream()
            translator.process_stream(streamer, translate_enabled=True)
        except KeyboardInterrupt:
            streamer.stop_stream()
            print("\n✅ Test complete!")
    
    elif choice == "5":
        audio_path = input("Path to gold standard audio file: ").strip()
        tester.test_gold_standard_translation(audio_path, target_language="es")
    else:
        print("Invalid choice")