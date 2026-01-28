"""
Translation File Matcher and Renamer
=====================================
Matches translation files to their source Portuguese transcripts by comparing
the first few sentences, then renames translation files to match the source.

USAGE:
    python match_translation_files.py --raw "C:/path/to/raw_transcripts" --translations "C:/path/to/translations"

Or run interactively (will prompt for folders).

OUTPUT:
    - Renames translation files to: {source_filename}_translation.txt
    - Creates a log of all matches made
    - Reports any unmatched files
"""

import os
import re
import argparse
from datetime import datetime
from difflib import SequenceMatcher
import unicodedata

# =============================================================================
# CONFIGURATION
# =============================================================================

# How many characters to compare from the beginning of each file
COMPARISON_LENGTH = 500  # First ~500 characters (roughly 3-5 sentences)

# Minimum similarity ratio to consider a match (0.0 to 1.0)
MINIMUM_SIMILARITY = 0.6  # 60% similarity threshold

# File extensions to look for
RAW_EXTENSIONS = ['.txt']
TRANSLATION_EXTENSIONS = ['.txt']

# =============================================================================
# TEXT NORMALIZATION
# =============================================================================

def normalize_text(text):
    """
    Normalize text for comparison by:
    - Converting to lowercase
    - Removing extra whitespace
    - Removing punctuation
    - Normalizing unicode characters
    """
    if not text:
        return ""
    
    # Convert to lowercase
    text = text.lower()
    
    # Normalize unicode (handle accented characters consistently)
    text = unicodedata.normalize('NFKD', text)
    
    # Remove punctuation but keep letters, numbers, spaces
    text = re.sub(r'[^\w\s]', ' ', text)
    
    # Collapse multiple spaces into one
    text = re.sub(r'\s+', ' ', text)
    
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text


def extract_comparison_text(filepath, length=COMPARISON_LENGTH):
    """
    Extract the first N characters from a file for comparison.
    Tries multiple encodings if needed.
    """
    encodings = ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']
    
    for encoding in encodings:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                content = f.read(length * 2)  # Read extra to ensure we have enough
                # Skip any BOM or header lines that might be metadata
                lines = content.split('\n')
                # Skip lines that look like headers/metadata
                text_lines = []
                for line in lines:
                    line = line.strip()
                    # Skip empty lines and lines that look like metadata
                    if not line:
                        continue
                    if line.startswith('=') or line.startswith('-') or line.startswith('#'):
                        continue
                    if ':' in line and len(line.split(':')[0]) < 30:
                        # Likely a "Label: value" metadata line
                        continue
                    text_lines.append(line)
                
                text = ' '.join(text_lines)[:length]
                return normalize_text(text)
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    print(f"  WARNING: Could not read {filepath} with any encoding")
    return ""


def calculate_similarity(text1, text2):
    """
    Calculate similarity ratio between two texts using SequenceMatcher.
    Returns a value between 0.0 (completely different) and 1.0 (identical).
    """
    if not text1 or not text2:
        return 0.0
    
    return SequenceMatcher(None, text1, text2).ratio()


# =============================================================================
# FILE MATCHING LOGIC
# =============================================================================

def get_files_in_folder(folder_path, extensions):
    """Get all files with specified extensions in a folder."""
    files = []
    for filename in os.listdir(folder_path):
        filepath = os.path.join(folder_path, filename)
        if os.path.isfile(filepath):
            ext = os.path.splitext(filename)[1].lower()
            if ext in extensions:
                files.append(filepath)
    return sorted(files)


def find_best_match(translation_path, raw_files, raw_texts):
    """
    Find the best matching raw file for a translation file.
    
    Returns: (best_match_path, similarity_score) or (None, 0) if no match found
    """
    trans_text = extract_comparison_text(translation_path)
    
    if not trans_text:
        return None, 0
    
    best_match = None
    best_score = 0
    
    for raw_path, raw_text in zip(raw_files, raw_texts):
        if not raw_text:
            continue
        
        score = calculate_similarity(trans_text, raw_text)
        
        if score > best_score:
            best_score = score
            best_match = raw_path
    
    return best_match, best_score


def generate_new_filename(raw_filename, translation_ext='.txt'):
    """
    Generate new translation filename based on raw filename.
    
    Example: "2026-01-05 - Sermon Title - Pastor.txt" 
          -> "2026-01-05 - Sermon Title - Pastor_translation.txt"
    """
    base, ext = os.path.splitext(raw_filename)
    return f"{base}_translation{ext}"


# =============================================================================
# MAIN MATCHING FUNCTION
# =============================================================================

def match_and_rename_translations(raw_folder, translations_folder, dry_run=True):
    """
    Match translation files to raw transcripts and rename them.
    
    Args:
        raw_folder: Path to folder containing raw Portuguese transcripts
        translations_folder: Path to folder containing translation files
        dry_run: If True, only show what would be done (don't actually rename)
    
    Returns:
        dict with match results and statistics
    """
    print("\n" + "=" * 70)
    print("TRANSLATION FILE MATCHER")
    print("=" * 70)
    print(f"\nRaw transcripts folder:  {raw_folder}")
    print(f"Translations folder:     {translations_folder}")
    print(f"Mode:                    {'DRY RUN (preview only)' if dry_run else 'LIVE (will rename files)'}")
    print("-" * 70)
    
    # Get all files
    raw_files = get_files_in_folder(raw_folder, RAW_EXTENSIONS)
    translation_files = get_files_in_folder(translations_folder, TRANSLATION_EXTENSIONS)
    
    print(f"\nFound {len(raw_files)} raw transcript files")
    print(f"Found {len(translation_files)} translation files")
    
    if not raw_files:
        print("\nERROR: No raw transcript files found!")
        return None
    
    if not translation_files:
        print("\nERROR: No translation files found!")
        return None
    
    # Pre-extract text from all raw files (for efficiency)
    print("\nExtracting text from raw files for comparison...")
    raw_texts = []
    for rf in raw_files:
        raw_texts.append(extract_comparison_text(rf))
    
    # Match each translation file
    print("\nMatching translation files to raw transcripts...")
    print("-" * 70)
    
    matches = []
    unmatched_translations = []
    unmatched_raw = set(raw_files)
    
    for trans_path in translation_files:
        trans_filename = os.path.basename(trans_path)
        
        # Skip if already has "_translation" in name
        if "_translation" in trans_filename.lower():
            print(f"\n⏭️  SKIP: {trans_filename}")
            print(f"   (Already has '_translation' in filename)")
            continue
        
        best_match, score = find_best_match(trans_path, raw_files, raw_texts)
        
        if best_match and score >= MINIMUM_SIMILARITY:
            raw_filename = os.path.basename(best_match)
            new_filename = generate_new_filename(raw_filename)
            new_path = os.path.join(translations_folder, new_filename)
            
            matches.append({
                'translation_old': trans_path,
                'translation_new': new_path,
                'raw_match': best_match,
                'similarity': score,
                'old_filename': trans_filename,
                'new_filename': new_filename,
            })
            
            # Remove from unmatched set
            if best_match in unmatched_raw:
                unmatched_raw.remove(best_match)
            
            print(f"\n✅ MATCH ({score*100:.1f}% similar):")
            print(f"   Translation: {trans_filename}")
            print(f"   Raw file:    {raw_filename}")
            print(f"   New name:    {new_filename}")
        else:
            unmatched_translations.append(trans_path)
            print(f"\n❌ NO MATCH: {trans_filename}")
            if best_match:
                print(f"   Best candidate: {os.path.basename(best_match)} ({score*100:.1f}% - below {MINIMUM_SIMILARITY*100:.0f}% threshold)")
            else:
                print(f"   Could not extract text for comparison")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nMatches found:           {len(matches)}")
    print(f"Unmatched translations:  {len(unmatched_translations)}")
    print(f"Unmatched raw files:     {len(unmatched_raw)}")
    
    if unmatched_translations:
        print("\n⚠️  Unmatched translation files:")
        for uf in unmatched_translations:
            print(f"   - {os.path.basename(uf)}")
    
    if unmatched_raw:
        print("\n⚠️  Raw files with no matching translation:")
        for uf in unmatched_raw:
            print(f"   - {os.path.basename(uf)}")
    
    # Perform renames (if not dry run)
    if matches:
        print("\n" + "-" * 70)
        
        if dry_run:
            print("DRY RUN - No files were renamed.")
            print("Run with --execute to actually rename files.")
        else:
            print("RENAMING FILES...")
            renamed_count = 0
            errors = []
            
            for match in matches:
                try:
                    # Check if target already exists
                    if os.path.exists(match['translation_new']):
                        print(f"   ⚠️  SKIP (target exists): {match['new_filename']}")
                        errors.append(f"Target exists: {match['new_filename']}")
                        continue
                    
                    os.rename(match['translation_old'], match['translation_new'])
                    print(f"   ✅ Renamed: {match['old_filename']} → {match['new_filename']}")
                    renamed_count += 1
                except Exception as e:
                    print(f"   ❌ ERROR renaming {match['old_filename']}: {e}")
                    errors.append(f"{match['old_filename']}: {e}")
            
            print(f"\nRenamed {renamed_count} of {len(matches)} files")
            if errors:
                print(f"Errors: {len(errors)}")
    
    # Save log
    log_filename = f"translation_match_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    log_path = os.path.join(translations_folder, log_filename)
    
    with open(log_path, 'w', encoding='utf-8') as f:
        f.write("TRANSLATION FILE MATCHING LOG\n")
        f.write("=" * 70 + "\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Raw folder: {raw_folder}\n")
        f.write(f"Translations folder: {translations_folder}\n")
        f.write(f"Mode: {'DRY RUN' if dry_run else 'EXECUTED'}\n")
        f.write("=" * 70 + "\n\n")
        
        f.write("MATCHES:\n")
        f.write("-" * 70 + "\n")
        for match in matches:
            f.write(f"Translation: {match['old_filename']}\n")
            f.write(f"  → Raw:     {os.path.basename(match['raw_match'])}\n")
            f.write(f"  → New:     {match['new_filename']}\n")
            f.write(f"  → Score:   {match['similarity']*100:.1f}%\n")
            f.write("\n")
        
        if unmatched_translations:
            f.write("\nUNMATCHED TRANSLATIONS:\n")
            f.write("-" * 70 + "\n")
            for uf in unmatched_translations:
                f.write(f"  - {os.path.basename(uf)}\n")
        
        if unmatched_raw:
            f.write("\nUNMATCHED RAW FILES:\n")
            f.write("-" * 70 + "\n")
            for uf in unmatched_raw:
                f.write(f"  - {os.path.basename(uf)}\n")
    
    print(f"\nLog saved: {log_path}")
    
    return {
        'matches': matches,
        'unmatched_translations': unmatched_translations,
        'unmatched_raw': list(unmatched_raw),
        'log_path': log_path,
    }


# =============================================================================
# INTERACTIVE MODE
# =============================================================================

def interactive_mode():
    """Run in interactive mode, prompting for folders."""
    print("\n" + "=" * 70)
    print("TRANSLATION FILE MATCHER - Interactive Mode")
    print("=" * 70)
    
    # Get raw transcripts folder
    print("\nEnter the path to the folder containing RAW PORTUGUESE TRANSCRIPTS:")
    print("(These are the official/source files with correct filenames)")
    raw_folder = input("\nRaw folder path: ").strip().strip('"').strip("'")
    
    if not os.path.isdir(raw_folder):
        print(f"ERROR: Folder not found: {raw_folder}")
        return
    
    # Get translations folder
    print("\nEnter the path to the folder containing TRANSLATION FILES:")
    print("(These are the files that need to be renamed)")
    trans_folder = input("\nTranslations folder path: ").strip().strip('"').strip("'")
    
    if not os.path.isdir(trans_folder):
        print(f"ERROR: Folder not found: {trans_folder}")
        return
    
    # First do a dry run
    print("\n" + "-" * 70)
    print("Running in DRY RUN mode first (preview only)...")
    print("-" * 70)
    
    results = match_and_rename_translations(raw_folder, trans_folder, dry_run=True)
    
    if results and results['matches']:
        print("\n" + "=" * 70)
        confirm = input("\nDo you want to EXECUTE these renames? (yes/no): ").strip().lower()
        
        if confirm in ['yes', 'y']:
            print("\nExecuting renames...")
            match_and_rename_translations(raw_folder, trans_folder, dry_run=False)
        else:
            print("\nCancelled. No files were renamed.")
    else:
        print("\nNo matches to process.")


# =============================================================================
# COMMAND LINE INTERFACE
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Match and rename translation files to their source transcripts.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (prompts for folders)
  python match_translation_files.py
  
  # Preview matches (dry run)
  python match_translation_files.py --raw "C:/transcripts" --translations "C:/translations"
  
  # Actually rename files
  python match_translation_files.py --raw "C:/transcripts" --translations "C:/translations" --execute
  
  # Adjust similarity threshold
  python match_translation_files.py --raw "C:/transcripts" --translations "C:/translations" --threshold 0.5
        """
    )
    
    parser.add_argument('--raw', '-r', 
                        help='Path to folder containing raw Portuguese transcripts')
    parser.add_argument('--translations', '-t', 
                        help='Path to folder containing translation files to rename')
    parser.add_argument('--execute', '-x', action='store_true',
                        help='Actually rename files (default is dry run)')
    parser.add_argument('--threshold', type=float, default=MINIMUM_SIMILARITY,
                        help=f'Minimum similarity threshold (0.0-1.0, default: {MINIMUM_SIMILARITY})')
    
    args = parser.parse_args()
    
    # Update threshold if specified
    global MINIMUM_SIMILARITY
    if args.threshold:
        MINIMUM_SIMILARITY = args.threshold
    
    # If both folders provided, run directly
    if args.raw and args.translations:
        if not os.path.isdir(args.raw):
            print(f"ERROR: Raw folder not found: {args.raw}")
            return
        if not os.path.isdir(args.translations):
            print(f"ERROR: Translations folder not found: {args.translations}")
            return
        
        match_and_rename_translations(args.raw, args.translations, dry_run=not args.execute)
    else:
        # Interactive mode
        interactive_mode()


if __name__ == "__main__":
    main()