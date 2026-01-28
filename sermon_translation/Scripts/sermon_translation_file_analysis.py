#!/usr/bin/env python3
"""
Speech Recognition Analyzer
===========================
Standalone tool for analyzing Google Speech API recognition accuracy.

Compares official Portuguese transcripts with Google Speech API output to identify:
1. Words NOT heard by Google (in official but not in Google output)
2. Words Google "invented" (in Google output but not in official) - likely mishearings
3. Fuzzy matching to find what Google probably meant to hear

Usage:
    python speech_recognition_analyzer.py --official transcript.txt --google translations.txt
    python speech_recognition_analyzer.py --official transcript.txt --google translations.txt --output report.txt
    python speech_recognition_analyzer.py --batch folder_with_paired_files/

Author: Claude (Anthropic)
Version: 1.0
Date: January 2026
"""

import argparse
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, Tuple


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class WordAnalysis:
    """Analysis result for a single word."""
    word: str
    count: int
    likely_matches: List[Tuple[str, float, str]]  # (matched_word, score, match_type)
    category: str  # 'theological', 'name', 'common', 'filler', 'unknown'


@dataclass
class ComparisonResult:
    """Complete comparison result between two transcripts."""
    official_word_count: int
    google_word_count: int
    common_words: Set[str]
    only_official: Set[str]  # Words Google missed
    only_google: Set[str]    # Words Google "invented" (mishearings)
    recognition_rate: float
    vocabulary_overlap: float
    missed_word_analysis: List[WordAnalysis]
    misheard_word_analysis: List[WordAnalysis]
    suggested_corrections: List[Tuple[str, str, float]]  # (google_heard, likely_meant, confidence)
    suggested_hints: List[str]  # Words to add to speech hints


# =============================================================================
# TEXT PROCESSING
# =============================================================================

def clean_text(text: str) -> str:
    """Normalize text for comparison."""
    text = text.lower()
    # Remove punctuation but keep accented characters
    text = re.sub(r'[^\w\sáàâãéèêíìîóòôõúùûüçñ]', ' ', text)
    text = ' '.join(text.split())
    return text


def extract_google_sources(file_content: str) -> str:
    """Extract SOURCE lines from Google translations file."""
    sources = []
    for line in file_content.split('\n'):
        if line.startswith('SOURCE:'):
            source_text = line.replace('SOURCE:', '').strip()
            sources.append(source_text)
    return ' '.join(sources)


def get_word_frequency(text: str) -> Counter:
    """Get word frequency from text."""
    words = clean_text(text).split()
    return Counter(words)


# =============================================================================
# SIMILARITY MATCHING
# =============================================================================

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculate Levenshtein (edit) distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def normalized_levenshtein(s1: str, s2: str) -> float:
    """Calculate normalized Levenshtein similarity (0-1, higher is more similar)."""
    if not s1 or not s2:
        return 0.0
    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    return 1 - (distance / max_len)


def phonetic_similarity_portuguese(s1: str, s2: str) -> float:
    """
    Estimate phonetic similarity for Portuguese words.
    This is a simplified approach - considers common sound equivalences.
    """
    # Portuguese phonetic equivalences (simplified)
    equivalences = [
        ('ç', 'ss'), ('ç', 's'),
        ('ss', 's'), ('s', 'z'),
        ('x', 'ch'), ('x', 'sh'), ('x', 's'),
        ('ch', 'x'),
        ('nh', 'n'), ('lh', 'l'),
        ('qu', 'k'), ('c', 'k'),
        ('g', 'j'),
        ('rr', 'r'),
        ('ão', 'am'), ('ões', 'oes'),
        ('ei', 'e'), ('ou', 'o'),
        ('ão', 'ao'),
    ]
    
    s1_normalized = s1.lower()
    s2_normalized = s2.lower()
    
    # Apply equivalences
    for eq1, eq2 in equivalences:
        s1_normalized = s1_normalized.replace(eq1, eq2)
        s2_normalized = s2_normalized.replace(eq1, eq2)
    
    # Calculate similarity on normalized versions
    return normalized_levenshtein(s1_normalized, s2_normalized)


def substring_match(short: str, long: str) -> float:
    """Check if short string is contained in long string."""
    short = short.lower()
    long = long.lower()
    
    if short in long:
        return len(short) / len(long)
    if long in short:
        return len(long) / len(short)
    return 0.0


def sequence_similarity(s1: str, s2: str) -> float:
    """Calculate sequence similarity using SequenceMatcher."""
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def combined_similarity(word1: str, word2: str) -> Tuple[float, str]:
    """
    Calculate combined similarity score and identify match type.
    Returns (score, match_type).
    """
    # Skip if lengths are too different (unlikely to be a match)
    len_ratio = min(len(word1), len(word2)) / max(len(word1), len(word2))
    if len_ratio < 0.5:
        return (0.0, 'none')
    
    # Calculate different similarity metrics
    levenshtein_sim = normalized_levenshtein(word1, word2)
    phonetic_sim = phonetic_similarity_portuguese(word1, word2)
    sequence_sim = sequence_similarity(word1, word2)
    substring_sim = substring_match(word1, word2)
    
    # Determine best match type and score
    scores = [
        (levenshtein_sim, 'levenshtein'),
        (phonetic_sim, 'phonetic'),
        (sequence_sim, 'sequence'),
        (substring_sim, 'substring'),
    ]
    
    best_score, best_type = max(scores, key=lambda x: x[0])
    
    # Weighted combination (phonetic is important for speech recognition)
    combined = (
        levenshtein_sim * 0.25 +
        phonetic_sim * 0.35 +
        sequence_sim * 0.25 +
        substring_sim * 0.15
    )
    
    return (combined, best_type if combined > 0.5 else 'none')


# =============================================================================
# WORD CATEGORIZATION
# =============================================================================

# Portuguese theological terms (subset for categorization)
THEOLOGICAL_TERMS = {
    'deus', 'jesus', 'cristo', 'espírito', 'santo', 'graça', 'salvação',
    'pecado', 'igreja', 'evangelho', 'bíblia', 'escrituras', 'apóstolo',
    'profeta', 'oração', 'fé', 'esperança', 'amor', 'batismo', 'ressurreição',
    'crucificação', 'redenção', 'santificação', 'justificação', 'glorificação',
    'trindade', 'encarnação', 'ascensão', 'aliança', 'pacto', 'sacramento',
    'comunhão', 'adoração', 'louvor', 'sermão', 'pregação', 'ministério',
    'gnosticismo', 'gnóstico', 'gnosis', 'epignosis', 'heresia', 'herético',
    'pneumático', 'cosmogonia', 'docetismo', 'carpocratiano', 'irineu',
}

# Biblical names and places
BIBLICAL_NAMES = {
    'paulo', 'pedro', 'joão', 'mateus', 'marcos', 'lucas', 'tiago',
    'abraão', 'moisés', 'davi', 'salomão', 'isaías', 'jeremias', 'daniel',
    'maria', 'josé', 'adão', 'eva', 'noé', 'elias', 'eliseu',
    'jerusalém', 'israel', 'judá', 'galileia', 'nazaré', 'belém',
    'éfeso', 'corinto', 'roma', 'filipos', 'tessalônica', 'colossenses',
    'gália', 'ásia', 'macedônia', 'antioquia', 'damasco',
}

# Common Portuguese filler words
FILLER_WORDS = {
    'né', 'então', 'assim', 'tipo', 'bem', 'ah', 'eh', 'uhm', 'uh',
    'olha', 'veja', 'sabe', 'entende', 'certo', 'tá', 'ok', 'bom',
    'realmente', 'basicamente', 'literalmente', 'obviamente',
}


def categorize_word(word: str) -> str:
    """Categorize a word by type."""
    word_lower = word.lower()
    
    if word_lower in THEOLOGICAL_TERMS:
        return 'theological'
    if word_lower in BIBLICAL_NAMES:
        return 'biblical_name'
    if word_lower in FILLER_WORDS:
        return 'filler'
    if len(word) <= 3:
        return 'short'
    
    return 'common'


# =============================================================================
# MAIN ANALYSIS
# =============================================================================

def find_likely_matches(
    word: str, 
    candidate_words: Set[str], 
    min_score: float = 0.6,
    max_matches: int = 3
) -> List[Tuple[str, float, str]]:
    """
    Find likely matches for a word from candidate set.
    Returns list of (matched_word, score, match_type).
    """
    matches = []
    
    for candidate in candidate_words:
        # Skip if same word
        if word.lower() == candidate.lower():
            continue
        
        # Skip very short words (less meaningful matches)
        if len(word) < 4 or len(candidate) < 4:
            continue
        
        score, match_type = combined_similarity(word, candidate)
        
        if score >= min_score:
            matches.append((candidate, score, match_type))
    
    # Sort by score descending, take top matches
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[:max_matches]


def analyze_transcripts(
    official_text: str, 
    google_text: str,
    min_word_length: int = 4,
    min_match_score: float = 0.6
) -> ComparisonResult:
    """
    Perform complete analysis comparing official and Google transcripts.
    """
    # Clean and tokenize
    official_clean = clean_text(official_text)
    google_clean = clean_text(google_text)
    
    official_words = official_clean.split()
    google_words = google_clean.split()
    
    official_set = set(official_words)
    google_set = set(google_words)
    
    # Basic set operations
    common_words = official_set & google_set
    only_official = official_set - google_set
    only_google = google_set - official_set
    
    # Calculate metrics
    recognition_rate = len(google_words) / len(official_words) if official_words else 0
    vocabulary_overlap = len(common_words) / len(official_set) if official_set else 0
    
    # Filter to significant words
    significant_official = {w for w in only_official if len(w) >= min_word_length}
    significant_google = {w for w in only_google if len(w) >= min_word_length}
    
    # Get word frequencies
    official_freq = get_word_frequency(official_text)
    google_freq = get_word_frequency(google_text)
    
    # Analyze missed words (in official but not in Google)
    missed_word_analysis = []
    for word in significant_official:
        matches = find_likely_matches(word, google_set, min_match_score)
        category = categorize_word(word)
        analysis = WordAnalysis(
            word=word,
            count=official_freq.get(word, 0),
            likely_matches=matches,
            category=category
        )
        missed_word_analysis.append(analysis)
    
    # Sort by frequency (most common missed words first)
    missed_word_analysis.sort(key=lambda x: x.count, reverse=True)
    
    # Analyze misheard words (in Google but not in official)
    misheard_word_analysis = []
    suggested_corrections = []
    
    for word in significant_google:
        matches = find_likely_matches(word, official_set, min_match_score)
        category = categorize_word(word)
        analysis = WordAnalysis(
            word=word,
            count=google_freq.get(word, 0),
            likely_matches=matches,
            category=category
        )
        misheard_word_analysis.append(analysis)
        
        # If we found a good match, suggest a correction
        if matches and matches[0][1] >= 0.7:
            suggested_corrections.append((word, matches[0][0], matches[0][1]))
    
    # Sort by frequency
    misheard_word_analysis.sort(key=lambda x: x.count, reverse=True)
    
    # Suggest words to add to speech hints
    # Focus on theological/biblical words that were missed
    suggested_hints = [
        analysis.word for analysis in missed_word_analysis
        if analysis.category in ('theological', 'biblical_name')
        and analysis.count >= 2  # Appears at least twice
    ]
    
    return ComparisonResult(
        official_word_count=len(official_words),
        google_word_count=len(google_words),
        common_words=common_words,
        only_official=only_official,
        only_google=only_google,
        recognition_rate=recognition_rate,
        vocabulary_overlap=vocabulary_overlap,
        missed_word_analysis=missed_word_analysis,
        misheard_word_analysis=misheard_word_analysis,
        suggested_corrections=suggested_corrections,
        suggested_hints=suggested_hints
    )


# =============================================================================
# REPORT GENERATION
# =============================================================================

def generate_report(
    result: ComparisonResult,
    official_filename: str,
    google_filename: str,
    detailed: bool = True
) -> str:
    """Generate a formatted analysis report."""
    lines = []
    
    # Header
    lines.append("=" * 80)
    lines.append("SPEECH RECOGNITION ANALYSIS REPORT")
    lines.append("=" * 80)
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Official Transcript: {official_filename}")
    lines.append(f"Google API Output: {google_filename}")
    lines.append("")
    
    # Summary Statistics
    lines.append("-" * 80)
    lines.append("SUMMARY STATISTICS")
    lines.append("-" * 80)
    lines.append(f"Official word count:     {result.official_word_count:,}")
    lines.append(f"Google word count:       {result.google_word_count:,}")
    lines.append(f"Recognition rate:        {result.recognition_rate:.1%}")
    lines.append(f"Vocabulary overlap:      {result.vocabulary_overlap:.1%}")
    lines.append(f"Words Google missed:     {len(result.only_official):,}")
    lines.append(f"Words Google 'invented': {len(result.only_google):,}")
    lines.append("")
    
    # Missed Words Analysis
    lines.append("-" * 80)
    lines.append("WORDS NOT HEARD BY GOOGLE (Top 50)")
    lines.append("-" * 80)
    lines.append("These words appear in the official transcript but Google didn't recognize them.")
    lines.append("")
    lines.append(f"{'Word':<25} {'Count':<8} {'Category':<15} {'Possible Reason'}")
    lines.append("-" * 80)
    
    for analysis in result.missed_word_analysis[:50]:
        # Determine possible reason
        if analysis.category == 'filler':
            reason = "Filler word (filtered by design)"
        elif analysis.category == 'short':
            reason = "Too short to reliably recognize"
        elif analysis.likely_matches:
            best_match = analysis.likely_matches[0]
            reason = f"Heard as '{best_match[0]}' ({best_match[1]:.0%})"
        elif analysis.category == 'theological':
            reason = "Theological term - add to hints"
        elif analysis.category == 'biblical_name':
            reason = "Biblical name - add to hints"
        else:
            reason = "Possibly fast/unclear speech"
        
        lines.append(f"{analysis.word:<25} {analysis.count:<8} {analysis.category:<15} {reason}")
    
    lines.append("")
    
    # Misheard Words Analysis
    lines.append("-" * 80)
    lines.append("WORDS GOOGLE 'INVENTED' - LIKELY MISHEARINGS (Top 50)")
    lines.append("-" * 80)
    lines.append("These words appear in Google's output but NOT in the official transcript.")
    lines.append("They are likely mishearings of actual words.")
    lines.append("")
    lines.append(f"{'Google Heard':<25} {'Count':<8} {'Likely Meant':<25} {'Confidence'}")
    lines.append("-" * 80)
    
    for analysis in result.misheard_word_analysis[:50]:
        if analysis.likely_matches:
            best_match = analysis.likely_matches[0]
            likely_meant = best_match[0]
            confidence = f"{best_match[1]:.0%} ({best_match[2]})"
        else:
            likely_meant = "???"
            confidence = "No match found"
        
        lines.append(f"{analysis.word:<25} {analysis.count:<8} {likely_meant:<25} {confidence}")
    
    lines.append("")
    
    # Suggested Corrections
    if result.suggested_corrections:
        lines.append("-" * 80)
        lines.append("SUGGESTED POST-RECOGNITION CORRECTIONS")
        lines.append("-" * 80)
        lines.append("Add these to your post-recognition correction dictionary:")
        lines.append("")
        lines.append("```python")
        lines.append("POST_RECOGNITION_CORRECTIONS = {")
        for google_heard, likely_meant, confidence in sorted(result.suggested_corrections, key=lambda x: x[2], reverse=True)[:30]:
            lines.append(f'    "{google_heard}": "{likely_meant}",  # {confidence:.0%} confidence')
        lines.append("}")
        lines.append("```")
        lines.append("")
    
    # Suggested Hints
    if result.suggested_hints:
        lines.append("-" * 80)
        lines.append("SUGGESTED SPEECH HINTS TO ADD")
        lines.append("-" * 80)
        lines.append("These theological/biblical terms were missed and should be added to speech hints:")
        lines.append("")
        for hint in result.suggested_hints[:20]:
            lines.append(f'    "{hint}",')
        lines.append("")
    
    # Detailed word lists (if requested)
    if detailed:
        lines.append("-" * 80)
        lines.append("COMPLETE WORD LISTS")
        lines.append("-" * 80)
        
        lines.append("")
        lines.append("All words in official but NOT heard by Google:")
        lines.append("-" * 40)
        sorted_official = sorted(result.only_official)
        for i, word in enumerate(sorted_official):
            lines.append(f"  {word}")
            if i >= 199:  # Limit to 200
                lines.append(f"  ... and {len(sorted_official) - 200} more")
                break
        
        lines.append("")
        lines.append("All words Google heard but NOT in official:")
        lines.append("-" * 40)
        sorted_google = sorted(result.only_google)
        for i, word in enumerate(sorted_google):
            lines.append(f"  {word}")
            if i >= 199:  # Limit to 200
                lines.append(f"  ... and {len(sorted_google) - 200} more")
                break
    
    lines.append("")
    lines.append("=" * 80)
    lines.append("END OF REPORT")
    lines.append("=" * 80)
    
    return '\n'.join(lines)


# =============================================================================
# FILE PROCESSING
# =============================================================================

def process_file_pair(
    official_path: str, 
    google_path: str,
    output_path: Optional[str] = None,
    detailed: bool = True
) -> ComparisonResult:
    """Process a pair of files and generate report."""
    print(f"Processing: {os.path.basename(official_path)}")
    
    # Read files
    with open(official_path, 'r', encoding='utf-8') as f:
        official_text = f.read()
    
    with open(google_path, 'r', encoding='utf-8') as f:
        google_content = f.read()
    
    # Check if Google file is translations format or plain text
    if 'SOURCE:' in google_content:
        google_text = extract_google_sources(google_content)
    else:
        google_text = google_content
    
    # Analyze
    result = analyze_transcripts(official_text, google_text)
    
    # Generate report
    report = generate_report(
        result,
        os.path.basename(official_path),
        os.path.basename(google_path),
        detailed=detailed
    )
    
    # Output
    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"  Report saved to: {output_path}")
    else:
        print(report)
    
    return result


def process_batch(folder_path: str, output_folder: Optional[str] = None):
    """
    Process multiple file pairs from a folder.
    Expects pairs like: sermon.txt and sermon_translations.txt
    """
    files = os.listdir(folder_path)
    
    # Find pairs
    pairs = []
    translations_files = [f for f in files if '_translations' in f.lower()]
    
    for trans_file in translations_files:
        # Find matching official file
        base_name = trans_file.replace('_translations', '').replace('_translation', '')
        
        # Try different matching patterns
        possible_matches = [
            base_name,
            base_name.replace('.txt', '') + '.txt',
        ]
        
        for match in possible_matches:
            if match in files and match != trans_file:
                pairs.append((
                    os.path.join(folder_path, match),
                    os.path.join(folder_path, trans_file)
                ))
                break
    
    print(f"Found {len(pairs)} file pairs to process")
    
    # Process each pair
    all_results = []
    for official_path, google_path in pairs:
        output_path = None
        if output_folder:
            base = os.path.splitext(os.path.basename(official_path))[0]
            output_path = os.path.join(output_folder, f"{base}_analysis.txt")
        
        result = process_file_pair(official_path, google_path, output_path)
        all_results.append((os.path.basename(official_path), result))
    
    # Generate summary
    if all_results:
        print("\n" + "=" * 80)
        print("BATCH SUMMARY")
        print("=" * 80)
        print(f"{'File':<40} {'Recog %':<10} {'Vocab %':<10} {'Missed':<10} {'Invented'}")
        print("-" * 80)
        
        for filename, result in all_results:
            short_name = filename[:37] + "..." if len(filename) > 40 else filename
            print(f"{short_name:<40} {result.recognition_rate:.1%}     {result.vocabulary_overlap:.1%}     {len(result.only_official):<10} {len(result.only_google)}")
        
        # Averages
        avg_recog = sum(r.recognition_rate for _, r in all_results) / len(all_results)
        avg_vocab = sum(r.vocabulary_overlap for _, r in all_results) / len(all_results)
        print("-" * 80)
        print(f"{'AVERAGE':<40} {avg_recog:.1%}     {avg_vocab:.1%}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Analyze Google Speech API recognition accuracy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Single file pair:
    python speech_recognition_analyzer.py --official sermon.txt --google sermon_translations.txt
  
  With output file:
    python speech_recognition_analyzer.py --official sermon.txt --google sermon_translations.txt --output report.txt
  
  Batch processing:
    python speech_recognition_analyzer.py --batch ./transcripts/
        """
    )
    
    parser.add_argument('--official', '-o', help='Path to official transcript file')
    parser.add_argument('--google', '-g', help='Path to Google API output file')
    parser.add_argument('--output', '-out', help='Path for output report (optional)')
    parser.add_argument('--batch', '-b', help='Folder containing paired files for batch processing')
    parser.add_argument('--brief', action='store_true', help='Generate brief report (no detailed word lists)')
    
    args = parser.parse_args()
    
    if args.batch:
        # Batch mode
        output_folder = args.output if args.output else None
        if output_folder and not os.path.exists(output_folder):
            os.makedirs(output_folder)
        process_batch(args.batch, output_folder)
    
    elif args.official and args.google:
        # Single file pair mode
        process_file_pair(
            args.official, 
            args.google, 
            args.output,
            detailed=not args.brief
        )
    
    else:
        parser.print_help()
        print("\nError: Please provide either --batch folder or both --official and --google files")
        sys.exit(1)


if __name__ == "__main__":
    main()