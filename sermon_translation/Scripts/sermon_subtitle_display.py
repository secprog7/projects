"""
Real-Time Sermon Subtitle Display
Displays translated sermon text in a clean, readable format
Similar to subtitles with 2-3 lines visible at a time
"""

import tkinter as tk
from tkinter import font, ttk
from datetime import datetime
import threading
import queue
from collections import deque


class SubtitleDisplay:
    """
    Clean subtitle-style display for real-time sermon translation
    
    Features:
    - 2-3 lines visible at a time
    - Smooth text updates
    - Large, readable font
    - Dark background for readability
    - Auto-scroll with controlled speed
    """
    
    def __init__(self, max_lines=3, font_size=24):
        """
        Initialize subtitle display
        
        Args:
            max_lines: Number of lines to display (2-3 recommended)
            font_size: Font size for text (24-32 recommended)
        """
        self.max_lines = max_lines
        self.font_size = font_size
        self.text_queue = queue.Queue()
        self.is_running = False
        
        # Store recent lines for display
        self.display_lines = deque(maxlen=max_lines)
        
        # Create main window
        self.root = tk.Tk()
        self.root.title("Sermon Translation Display")
        self.root.configure(bg='black')
        
        # Set window size and position (bottom of screen, wide)
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        
        window_height = 200  # Enough for 2-3 lines
        window_width = int(screen_width * 0.8)  # 80% of screen width
        
        # Position at bottom center
        x_position = (screen_width - window_width) // 2
        y_position = screen_height - window_height - 100
        
        self.root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")
        
        # Make window stay on top
        self.root.attributes('-topmost', True)
        
        # Create main frame
        main_frame = tk.Frame(self.root, bg='black')
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # Configure custom font
        self.display_font = font.Font(
            family="Arial",
            size=self.font_size,
            weight="bold"
        )
        
        # Create text display label
        self.text_label = tk.Label(
            main_frame,
            text="",
            font=self.display_font,
            fg='white',
            bg='black',
            justify='center',
            wraplength=window_width - 40,  # Wrap text to fit window
            anchor='center'
        )
        self.text_label.pack(expand=True)
        
        # Add language indicator
        self.lang_label = tk.Label(
            self.root,
            text="",
            font=('Arial', 10),
            fg='gray',
            bg='black'
        )
        self.lang_label.pack(side=tk.BOTTOM, pady=5)
        
        # Control buttons frame
        control_frame = tk.Frame(self.root, bg='black')
        control_frame.pack(side=tk.BOTTOM, pady=5)
        
        # Clear button
        self.clear_btn = tk.Button(
            control_frame,
            text="Clear",
            command=self.clear_display,
            bg='gray20',
            fg='white',
            font=('Arial', 10)
        )
        self.clear_btn.pack(side=tk.LEFT, padx=5)
        
        # Font size controls
        tk.Label(control_frame, text="Font:", bg='black', fg='white', font=('Arial', 10)).pack(side=tk.LEFT, padx=5)
        
        self.decrease_font_btn = tk.Button(
            control_frame,
            text="-",
            command=self.decrease_font,
            bg='gray20',
            fg='white',
            font=('Arial', 10),
            width=3
        )
        self.decrease_font_btn.pack(side=tk.LEFT, padx=2)
        
        self.increase_font_btn = tk.Button(
            control_frame,
            text="+",
            command=self.increase_font,
            bg='gray20',
            fg='white',
            font=('Arial', 10),
            width=3
        )
        self.increase_font_btn.pack(side=tk.LEFT, padx=2)
        
        # Start processing thread
        self.is_running = True
        self.update_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.update_thread.start()
        
    def set_language(self, source_lang, target_lang):
        """Set language indicator"""
        self.lang_label.config(text=f"{source_lang} → {target_lang}")
    
    def add_text(self, text, language_label=""):
        """
        Add new text to display
        
        Args:
            text: Text to display
            language_label: Optional label (e.g., "EN:", "PT:")
        """
        if text and text.strip():
            self.text_queue.put((text, language_label))
    
    def _process_queue(self):
        """Process incoming text from queue"""
        while self.is_running:
            try:
                text, label = self.text_queue.get(timeout=0.1)
                self._update_display(text, label)
            except queue.Empty:
                continue
    
    def _update_display(self, text, label=""):
        """
        Update the display with new text
        Implements smooth scrolling with 2-3 line limit
        """
        # Format text with label if provided
        formatted_text = f"{label} {text}" if label else text
        
        # Add to display lines (automatically removes oldest if > max_lines)
        self.display_lines.append(formatted_text)
        
        # Update display
        display_text = "\n".join(self.display_lines)
        
        # Update label in main thread
        self.root.after(0, self._safe_update_label, display_text)
    
    def _safe_update_label(self, text):
        """Safely update label from main thread"""
        self.text_label.config(text=text)
    
    def clear_display(self):
        """Clear all displayed text"""
        self.display_lines.clear()
        self.text_label.config(text="")
    
    def increase_font(self):
        """Increase font size"""
        self.font_size = min(self.font_size + 2, 48)
        self.display_font.configure(size=self.font_size)
    
    def decrease_font(self):
        """Decrease font size"""
        self.font_size = max(self.font_size - 2, 16)
        self.display_font.configure(size=self.font_size)
    
    def run(self):
        """Start the display window"""
        self.root.mainloop()
    
    def stop(self):
        """Stop the display"""
        self.is_running = False
        self.root.quit()


class DualLanguageDisplay(SubtitleDisplay):
    """
    Extended display showing both source and translation
    Useful for bilingual audiences
    """
    
    def __init__(self, max_lines=3, font_size=20):
        """Initialize dual language display"""
        super().__init__(max_lines=max_lines, font_size=font_size)
        
        # Modify layout for dual language
        self.text_label.pack_forget()
        
        # Create two separate text areas
        text_frame = tk.Frame(self.root, bg='black')
        text_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Source language (smaller, top)
        self.source_label = tk.Label(
            text_frame,
            text="",
            font=font.Font(family="Arial", size=self.font_size - 4),
            fg='lightgray',
            bg='black',
            justify='center',
            wraplength=self.root.winfo_screenwidth() * 0.8 - 40
        )
        self.source_label.pack(pady=5)
        
        # Target language (larger, bottom)
        self.target_label = tk.Label(
            text_frame,
            text="",
            font=self.display_font,
            fg='white',
            bg='black',
            justify='center',
            wraplength=self.root.winfo_screenwidth() * 0.8 - 40
        )
        self.target_label.pack(pady=5)
        
        self.current_source = deque(maxlen=max_lines)
        self.current_target = deque(maxlen=max_lines)
    
    def add_translation_pair(self, source_text, target_text):
        """
        Add a pair of source and translation text
        
        Args:
            source_text: Original language text
            target_text: Translated text
        """
        self.current_source.append(source_text)
        self.current_target.append(target_text)
        
        source_display = "\n".join(self.current_source)
        target_display = "\n".join(self.current_target)
        
        self.root.after(0, self._update_dual_display, source_display, target_display)
    
    def _update_dual_display(self, source_text, target_text):
        """Update both displays"""
        self.source_label.config(text=source_text)
        self.target_label.config(text=target_text)
    
    def clear_display(self):
        """Clear both displays"""
        self.current_source.clear()
        self.current_target.clear()
        self.source_label.config(text="")
        self.target_label.config(text="")


# Demo/Test function
def demo_display():
    """Demo the subtitle display"""
    import time
    
    print("Starting Subtitle Display Demo...")
    print("Close the window to exit.\n")
    
    # Create display
    display = SubtitleDisplay(max_lines=3, font_size=28)
    display.set_language("English", "Portuguese")
    
    # Sample sermon texts
    sample_texts = [
        ("EN: Let us turn to the book of Romans", "PT: Vamos ao livro de Romanos"),
        ("EN: Chapter three, verse twenty-three", "PT: Capítulo três, versículo vinte e três"),
        ("EN: For all have sinned and fall short of the glory of God", "PT: Pois todos pecaram e carecem da glória de Deus"),
        ("EN: Being justified freely by His grace", "PT: Sendo justificados gratuitamente pela Sua graça"),
        ("EN: Through the redemption that is in Christ Jesus", "PT: Mediante a redenção que há em Cristo Jesus"),
    ]
    
    # Simulate real-time translation in a separate thread
    def simulate_sermon():
        time.sleep(2)  # Wait for window to appear
        for source, target in sample_texts:
            display.add_text(target)
            time.sleep(3)  # 3 seconds between segments
    
    demo_thread = threading.Thread(target=simulate_sermon, daemon=True)
    demo_thread.start()
    
    # Run display
    display.run()


def demo_dual_display():
    """Demo the dual language display"""
    import time
    
    print("Starting Dual Language Display Demo...")
    print("Close the window to exit.\n")
    
    # Create dual display
    display = DualLanguageDisplay(max_lines=2, font_size=22)
    display.set_language("English", "Portuguese")
    
    # Sample texts
    sample_pairs = [
        ("Let us turn to the book of Romans", "Vamos ao livro de Romanos"),
        ("Chapter three, verse twenty-three", "Capítulo três, versículo vinte e três"),
        ("For all have sinned", "Pois todos pecaram"),
        ("and fall short of the glory of God", "e carecem da glória de Deus"),
        ("Being justified freely by His grace", "Sendo justificados gratuitamente pela Sua graça"),
    ]
    
    def simulate_sermon():
        time.sleep(2)
        for source, target in sample_pairs:
            display.add_translation_pair(source, target)
            time.sleep(3)
    
    demo_thread = threading.Thread(target=simulate_sermon, daemon=True)
    demo_thread.start()
    
    display.run()


if __name__ == "__main__":
    print("Subtitle Display Options:")
    print("1. Single Language (Translation Only)")
    print("2. Dual Language (Source + Translation)")
    
    choice = input("\nSelect option (1 or 2): ").strip()
    
    if choice == "2":
        demo_dual_display()
    else:
        demo_display()