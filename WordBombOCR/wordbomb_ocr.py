# WordBomb OCR Cheat (Windows, CustomTkinter, PyInstaller‑ready)
# --------------------------------------------------------------------------------------
# Modern dark dashboard UI with CustomTkinter
# - Two OCR regions: A is REQUIRED, B is OPTIONAL (used only if set)
# - Supports 2‑ and 3‑letter prompts (fast n‑gram index)
# - Top‑K suggestions + F8 hotkey to auto‑type best word
# - OCR caching to skip redundant recognitions between frames
# - Robust startup (no pre‑UI popups), helpful status bar, safe threading
# - Hard‑pins Tesseract paths and passes --tessdata-dir to avoid model errors
# - PyInstaller notes at bottom
#
# Dependencies
#   pip install pillow pytesseract pyautogui pynput customtkinter
#
# Project layout for bundling
#   project_root/
#     wordbomb_ocr.py  (this file)
#     vendor/
#       tesseract/
#         tesseract.exe
#         tessdata/
#           eng.traineddata
#           ... (other languages if needed)
#     LICENSE   (Apache‑2.0, optional but recommended)
#     NOTICE.txt (optional attribution)

import os
import sys
import time
import threading
import hashlib
import subprocess
from collections import defaultdict, Counter

import customtkinter as ctk
from tkinter import filedialog, messagebox

import pyautogui
from PIL import Image, ImageOps, ImageFilter
import pytesseract
from pynput import keyboard as pynput_keyboard

# ---------------------
# Config / constants
# ---------------------
DEBUG = False
LOOP_INTERVAL = 0.18
TOP_K = 5
THRESH = 170
UPSCALE = 2
ENABLE_CHAR_CORRECTION = True

LETTER_FREQ = Counter("ETAOINSHRDLCUMWFGYPBVKJXQZ")

# OCR common confusions
OCR_MAP = {
    "0": "O", "1": "I", "5": "S", "6": "G", "8": "B",
    "|": "I", "l": "I", "!": "I"
}

# ---------------------
# Paths & Tesseract wiring
# ---------------------

def resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base, *parts)

TESS_DIR = resource_path("vendor", "tesseract")
TESSEXEC = os.path.join(TESS_DIR, "tesseract.exe")
TESSDATA_DIR = os.path.join(TESS_DIR, "tessdata")
TESSDATA_DIR = os.path.normpath(TESSDATA_DIR).replace('\\', '/')

pytesseract.pytesseract.tesseract_cmd = TESSEXEC
os.environ["TESSDATA_PREFIX"] = os.path.normpath(TESS_DIR)

# Build tess config as a safe joined string (no embedded quotes)
TESS_CONFIG = " ".join([
    "--oem", "3",
    "--psm", "8",
    "--tessdata-dir", TESSDATA_DIR,
    "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "-c", "tessedit_char_blacklist=0123456789",
])

# ---------------------
# Global state
# ---------------------
selected_regions = [
    {"x1": None, "y1": None, "x2": None, "y2": None},  # Region A (required)
    {"x1": None, "y1": None, "x2": None, "y2": None},  # Region B (optional)
]

word_list = []
ngram_index = {2: defaultdict(list), 3: defaultdict(list)}
typed_history = set()
used_words = set()

best_current_word = ""
ocr_running = False
save_images = True

last_hashes = [None, None]
last_tokens = ["", ""]

# Advanced prompt correction state
last_prompt_before_typing = ""
prompt_retry_count = 0
MAX_PROMPT_RETRIES = 3

# UI handles
root = None
label_output = None
label_regionA = None
label_regionB = None
label_dict = None
words_frame = None
length_entry = None
used_letters_label = None
save_img_button = None
char_corr_button = None
btn_start = None
btn_stop = None
status_label = None

# UI caches
last_ui_list = []

kb_listener = None

# ---------------------
# Utility
# ---------------------

def dprint(*args):
    if DEBUG:
        print("[DEBUG]", *args)

# ---------------------
# Dictionary / Indexing
# ---------------------

def build_ngram_index(words):
    ngram_index[2].clear(); ngram_index[3].clear()
    for w in words:
        u = w.upper()
        if not u.isalpha():
            continue
        L = len(u)
        if L >= 2:
            for i in range(L - 1):
                ngram_index[2][u[i:i+2]].append(u)
        if L >= 3:
            for i in range(L - 2):
                ngram_index[3][u[i:i+3]].append(u)

def load_dictionary():
    global word_list
    path = filedialog.askopenfilename(title="Select dictionary (.txt)", filetypes=[("Text Files", "*.txt")])
    if not path:
        return
    with open(path, 'r', encoding='utf-8') as f:
        words = [line.strip() for line in f if line.strip()]
    words = sorted(set(w.upper() for w in words if w.isalpha()))
    word_list = words
    build_ngram_index(word_list)
    if label_dict:
        label_dict.configure(text=f"Loaded {len(word_list)} words (2/3‑gram indexed)")

# ---------------------
# Typing & Scoring
# ---------------------

def type_text(text):
    global last_prompt_before_typing, prompt_retry_count
    if not text:
        return
    last_prompt_before_typing = best_current_word if best_current_word else ""
    prompt_retry_count = 0
    typed_history.update(set(text.upper()))
    used_words.add(text.upper())
    update_used_letters_display()
    time.sleep(0.08)
    pyautogui.write(text, interval=0.01)
    pyautogui.press('enter')

def update_used_letters_display():
    if used_letters_label:
        letters = ''.join(sorted(typed_history))
        used_letters_label.configure(text=f"Used: {letters}")

def score_word(word, used_letters):
    unique = set(word)
    return (
        len(unique - used_letters),
        sum(LETTER_FREQ.get(ch, 0) for ch in unique),
        -len(word),
    )

# ---------------------
# Imaging / OCR helpers
# ---------------------

def region_to_image(r):
    x1, y1, x2, y2 = r["x1"], r["y1"], r["x2"], r["y2"]
    if None in (x1, y1, x2, y2):
        return None
    x, y = int(min(x1, x2)), int(min(y1, y2))
    w, h = int(abs(x2 - x1)), int(abs(y2 - y1))
    if w <= 0 or h <= 0:
        return None
    img = pyautogui.screenshot(region=(x, y, w, h)).convert('L')
    img = img.resize((max(1, int(w * UPSCALE)), max(1, int(h * UPSCALE))), Image.LANCZOS)
    img = ImageOps.autocontrast(img, cutoff=1)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    img = img.point(lambda p: 255 if p > THRESH else 0)
    return img

def img_hash(img):
    return hashlib.blake2s(img.tobytes(), digest_size=8).digest()

def try_alternative_ocr_configs(img):
    configs = [
        " ".join(["--oem", "3", "--psm", "6", "--tessdata-dir", TESSDATA_DIR, "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-c", "tessedit_char_blacklist=0123456789", "-c", "textord_heavy_nr=2", "-c", "textord_min_linesize=1"]),
        " ".join(["--oem", "1", "--psm", "6", "--tessdata-dir", TESSDATA_DIR, "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-c", "tessedit_char_blacklist=0123456789"]),
        " ".join(["--oem", "3", "--psm", "13", "--tessdata-dir", TESSDATA_DIR, "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-c", "tessedit_char_blacklist=0123456789", "-c", "textord_heavy_nr=1"]),
        " ".join(["--oem", "3", "--psm", "8", "--tessdata-dir", TESSDATA_DIR, "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-c", "tessedit_char_blacklist=0123456789", "-c", "textord_heavy_nr=0"]),
    ]
    best_result = ""
    best_score = -1
    for cfg in configs:
        try:
            raw = pytesseract.image_to_string(img, config=cfg).upper()
            letters = [OCR_MAP.get(ch, ch) for ch in raw if 'A' <= ch <= 'Z']
            if not letters:
                continue
            result = "".join(letters)[:3]
            score = len(result) * 10
            for ch in result:
                score += (3 if ch in 'ETAOIN' else 2 if ch in 'SHRDLU' else 1 if ch in 'CMFWY' else 0)
            if score > best_score:
                best_score = score
                best_result = result
        except Exception:
            continue
    return best_result

def postprocess_letters(letters):
    if not ENABLE_CHAR_CORRECTION:
        return letters
    processed = []
    for i, ch in enumerate(letters):
        c = ch
        if ch == 'L':
            if len(letters) == 1:
                c = 'I'
        elif ch == 'U':
            c = 'O'
        processed.append(c)
    return processed

def ocr_token(img, max_len=3):
    # Try multiple configs and pick best by heuristic
    configs = [
        TESS_CONFIG,
        " ".join(["--oem", "3", "--psm", "7", "--tessdata-dir", TESSDATA_DIR, "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-c", "tessedit_char_blacklist=0123456789"]),
        " ".join(["--oem", "1", "--psm", "8", "--tessdata-dir", TESSDATA_DIR, "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-c", "tessedit_char_blacklist=0123456789"]),
        " ".join(["--oem", "3", "--psm", "6", "--tessdata-dir", TESSDATA_DIR, "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-c", "tessedit_char_blacklist=0123456789"]),
        " ".join(["--oem", "3", "--psm", "13", "--tessdata-dir", TESSDATA_DIR, "-c", "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ", "-c", "tessedit_char_blacklist=0123456789"]),
    ]
    best_result = ""
    best_score = -1
    for cfg in configs:
        try:
            raw = pytesseract.image_to_string(img, config=cfg).upper()
            letters = [OCR_MAP.get(ch, ch) for ch in raw if 'A' <= ch <= 'Z']
            if not letters:
                continue
            letters = postprocess_letters(letters)
            result = "".join(letters)[:max_len]
            score = len(result) * 10
            for ch in result:
                score += (2 if ch in 'ETAOIN' else 1 if ch in 'SHRDLU' else 0.5 if ch in 'CMFWY' else 0)
            if 'L' in result and len(result) == 1:
                score -= 3
            if 'U' in result:
                score -= 2
            if score > best_score:
                best_score = score
                best_result = result
        except Exception:
            continue
    return best_result

def detect_token_from_regions():
    if None in selected_regions[0].values():
        return ""
    tokens = []
    for i, r in enumerate(selected_regions):
        img = region_to_image(r)
        if img is None:
            tokens.append("")
            continue
        h = img_hash(img)
        if h == last_hashes[i]:
            tokens.append(last_tokens[i])
        else:
            tok = ocr_token(img, max_len=3)
            last_hashes[i] = h
            last_tokens[i] = tok
            tokens.append(tok)
        if save_images and tokens[-1]:
            try:
                os.makedirs("ocr_images", exist_ok=True)
                ts = time.strftime("%Y%m%d-%H%M%S")
                img.save(f"ocr_images/region_{'AB'[i]}_{ts}.png")
            except Exception:
                pass
    ranked = sorted((t for t in tokens if t), key=lambda t: (-len(t), t))
    for t in ranked:
        if len(t) in (3, 2):
            return t
    return ranked[0] if ranked else ""

# ---------------------
# UI helpers
# ---------------------

def update_output(prompt_text, word_matches=None):
    suffix = ""
    if last_prompt_before_typing and prompt_retry_count > 0:
        suffix = "  [Auto-correcting…]"
    if label_output:
        label_output.configure(text=f"Prompt: {prompt_text}{suffix}")
    if word_matches is not None:
        render_suggestions(word_matches)

def render_suggestions(word_matches):
    """Render word suggestions in the words frame."""
    global last_ui_list
    top = word_matches[:TOP_K]
    if top == last_ui_list:
        return
    last_ui_list = top
    if words_frame:
        for w in list(words_frame.winfo_children()):
            w.destroy()
        for w in top:
            ctk.CTkButton(
                words_frame,
                text=f"📝 {w}",
                width=280,  # Reduced width to fit better
                font=(FONT_FAMILY, 12),  # Added Satoshi font
                command=lambda ww=w: threading.Thread(target=type_text, args=(ww,), daemon=True).start()
            ).pack(pady=3, padx=8, fill='x')  # Added horizontal padding

def fmt_region(r):
    if None in r.values():
        return "Not set"
    return f"{r['x1']},{r['y1']} → {r['x2']},{r['y2']}"

def update_region_labels():
    if label_regionA:
        label_regionA.configure(text=f"Region A: {fmt_region(selected_regions[0])}")
    if label_regionB:
        label_regionB.configure(text=f"Region B (optional): {fmt_region(selected_regions[1])}")

# ---------------------
# Core capture loop & controls with correction heuristics
# ---------------------

def capture_and_match_once(min_length=1):
    global best_current_word, last_prompt_before_typing, prompt_retry_count
    try:
        token = detect_token_from_regions()
        if not token:
            best_current_word = ""
            update_output("no prompt detected.", [])
            return

        # If the same prompt persists after typing, try corrective OCR up to N times
        if (last_prompt_before_typing and token == last_prompt_before_typing and prompt_retry_count < MAX_PROMPT_RETRIES):
            prompt_retry_count += 1
            # Use Region A image to attempt correction
            base_img = region_to_image(selected_regions[0])
            if base_img is not None:
                alt = try_alternative_ocr_configs(base_img)
                if alt and alt != token:
                    token = alt
                    last_prompt_before_typing = ""
                    prompt_retry_count = 0

        L = len(token)
        words = ngram_index.get(L, {}).get(token, [])
        matches = [w for w in words if len(w) >= min_length and w not in used_words]
        if matches:
            matches.sort(key=lambda w: score_word(w, typed_history), reverse=True)
            best_current_word = matches[0]
            update_output(f"{token}", matches)
        else:
            best_current_word = ""
            update_output(f"{token}", [])
    except Exception as e:
        best_current_word = ""
        update_output(f"err: {e}", [])
        dprint("Exception in capture loop:", e)

def start_live_ocr():
    global ocr_running
    if None in selected_regions[0].values():
        messagebox.showerror("Error", "OCR region A is not set.")
        return
    ocr_running = True
    if status_label:
        status_label.configure(text="Status: Live OCR running")
    if btn_start:
        btn_start.configure(state="disabled")
    if btn_stop:
        btn_stop.configure(state="normal")

    def loop():
        while ocr_running:
            try:
                # Read desired min length if available
                min_len = 1
                try:
                    if length_entry: 
                        min_len = max(1, int(length_entry.get()))
                except Exception:
                    min_len = 1
                capture_and_match_once(min_length=min_len)
                time.sleep(LOOP_INTERVAL)
            except Exception as e:
                dprint("Loop exception:", e)
                time.sleep(LOOP_INTERVAL)
    threading.Thread(target=loop, daemon=True).start()

def stop_live_ocr():
    global ocr_running
    ocr_running = False
    if status_label:
        status_label.configure(text="Status: Stopped")
    if btn_start:
        btn_start.configure(state="normal")
    if btn_stop:
        btn_stop.configure(state="disabled")

def clear_used_words():
    used_words.clear()
    messagebox.showinfo("Cleared", "Used word history cleared.")

def tesseract_status():
    """Return (found, version_str, langs_list_or_none). Non‑fatal if missing."""
    if not os.path.isfile(TESSEXEC):
        if DEBUG:
            print(f"[DEBUG] Tesseract not found at: {TESSEXEC}")
        return False, None, None
    try:
        ver = subprocess.check_output([TESSEXEC, "-v"], stderr=subprocess.STDOUT, text=True, timeout=3)
        try:
            langs = subprocess.check_output([TESSEXEC, "--list-langs"], stderr=subprocess.STDOUT, text=True, timeout=3)
            langs_list = [ln.strip() for ln in langs.splitlines() if ln.strip() and not ln.lower().startswith("list of ")]
        except Exception:
            langs_list = None
        return True, ver.splitlines()[0].strip(), langs_list
    except Exception as e:
        if DEBUG:
            print(f"[DEBUG] Error running Tesseract: {e}")
        return True, None, None

def toggle_image_saving():
    global save_images
    save_images = not save_images
    if save_img_button:
        save_img_button.configure(text=f"Save images: {'ON' if save_images else 'OFF'}")

def toggle_char_correction():
    global ENABLE_CHAR_CORRECTION
    ENABLE_CHAR_CORRECTION = not ENABLE_CHAR_CORRECTION
    if char_corr_button:
        char_corr_button.configure(text=f"Char correction: {'ON' if ENABLE_CHAR_CORRECTION else 'OFF'}")

def force_auto_correct():
    """Manually trigger auto-correction for the current prompt."""
    global last_prompt_before_typing, prompt_retry_count
    if best_current_word:
        last_prompt_before_typing = best_current_word
        prompt_retry_count = 0
        messagebox.showinfo("Auto-correct", f"Will auto-correct '{best_current_word}' on next detection if it persists.")
    else:
        messagebox.showwarning("Auto-correct", "No current prompt to auto-correct.")

# ---------------------
# Region selection (A required, B optional)
# ---------------------

def on_select_region(idx: int):
    messagebox.showinfo("Region select", f"Click top-left and bottom-right of OCR area {'AB'[idx]}.")
    root.withdraw()

    def get_mouse_clicks():
        coords = []
        def on_click(x, y, button, pressed):
            if pressed:
                coords.append((x, y))
                if len(coords) == 2:
                    selected_regions[idx]["x1"], selected_regions[idx]["y1"] = coords[0]
                    selected_regions[idx]["x2"], selected_regions[idx]["y2"] = coords[1]
                    update_region_labels()
                    try:
                        mouse_listener.stop()
                    except Exception:
                        pass
                    root.after(0, root.deiconify)
        from pynput import mouse
        mouse_listener = mouse.Listener(on_click=on_click)
        mouse_listener.start()
        mouse_listener.join()

    threading.Thread(target=get_mouse_clicks, daemon=True).start()

# ---------------------
# UI with CustomTkinter (modern dashboard)
# ---------------------

def build_ui():
    global root, label_output, label_regionA, label_regionB, label_dict, words_frame
    global length_entry, used_letters_label, save_img_button, char_corr_button, btn_start, btn_stop, status_label

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("green")
    
    # Font configuration with fallbacks
    try:
        # Try to use Satoshi font, fallback to system fonts if not available
        import tkinter.font as tkfont
        available_fonts = tkfont.families()
        if "Satoshi" in available_fonts:
            FONT_FAMILY = "Satoshi"
        elif "Segoe UI" in available_fonts:
            FONT_FAMILY = "Segoe UI"
        else:
            FONT_FAMILY = "TkDefaultFont"
    except:
        FONT_FAMILY = "Segoe UI"

    root = ctk.CTk()
    root.title("WordBomb OCR — Dashboard")
    root.geometry("800x600")  # Optimized size for better UI fit
    root.minsize(700, 500)     # Minimum size to prevent UI cutoff
    root.attributes('-topmost', True)

    # Layout: Sidebar + Main
    root.grid_columnconfigure(0, weight=0, minsize=250)  # Dynamic sidebar width with larger minimum
    root.grid_columnconfigure(1, weight=1, minsize=600)  # Minimum main content width
    root.grid_rowconfigure(0, weight=1)

    # Sidebar
    sidebar = ctk.CTkFrame(root, corner_radius=12)  # Dynamic width based on content
    sidebar.grid(row=0, column=0, sticky="nsw", padx=16, pady=12)  # Increased left padding
    sidebar.grid_columnconfigure(0, weight=1)  # Allow sidebar to expand

    ctk.CTkLabel(sidebar, text="WordBomb OCR", font=(FONT_FAMILY, 20, "bold")).pack(pady=(8,16), padx=16)  # Added horizontal padding
    btn_start = ctk.CTkButton(sidebar, text="▶ Start OCR", command=start_live_ocr, font=(FONT_FAMILY, 12))
    btn_start.pack(pady=6, padx=16, fill='x')  # Increased horizontal padding
    btn_stop = ctk.CTkButton(sidebar, text="⏹ Stop OCR", command=stop_live_ocr, font=(FONT_FAMILY, 12))
    btn_stop.pack(pady=6, padx=16, fill='x')
    ctk.CTkButton(sidebar, text="📚 Load Dictionary", command=load_dictionary, font=(FONT_FAMILY, 12)).pack(pady=6, padx=16, fill='x')
    
    # Dictionary status label
    label_dict = ctk.CTkLabel(sidebar, text="No dictionary loaded", font=(FONT_FAMILY, 11))
    label_dict.pack(pady=(4,12), padx=16)

    ctk.CTkButton(sidebar, text="📍 Select Region A", command=lambda: on_select_region(0), font=(FONT_FAMILY, 11)).pack(pady=(16,6), padx=16, fill='x')
    ctk.CTkButton(sidebar, text="📍 Select Region B", command=lambda: on_select_region(1), font=(FONT_FAMILY, 11)).pack(pady=6, padx=16, fill='x')

    # Region status labels
    label_regionA = ctk.CTkLabel(sidebar, text="Region A: Not set", font=(FONT_FAMILY, 10))
    label_regionA.pack(pady=(6,2), padx=16)
    label_regionB = ctk.CTkLabel(sidebar, text="Region B: Not set", font=(FONT_FAMILY, 10))
    label_regionB.pack(pady=(0,12), padx=16)

    save_img_button = ctk.CTkButton(sidebar, text=f"Save images: {'ON' if save_images else 'OFF'}", command=toggle_image_saving, font=(FONT_FAMILY, 11))
    save_img_button.pack(pady=(0,6), padx=16, fill='x')
    char_corr_button = ctk.CTkButton(sidebar, text=f"Char correction: {'ON' if ENABLE_CHAR_CORRECTION else 'OFF'}", command=toggle_char_correction, font=(FONT_FAMILY, 11))
    char_corr_button.pack(pady=6, padx=16, fill='x')
    
    # Used letters label
    used_letters_label = ctk.CTkLabel(sidebar, text="Used: ", font=(FONT_FAMILY, 10))
    used_letters_label.pack(pady=(12,8), padx=16)

    # Main content
    main = ctk.CTkFrame(root, corner_radius=12)
    main.grid(row=0, column=1, sticky="nsew", padx=8, pady=12)  # Reduced left padding to bring closer to sidebar
    main.grid_columnconfigure(0, weight=1)
    main.grid_rowconfigure(5, weight=1)

    header = ctk.CTkLabel(main, text="Overview", font=(FONT_FAMILY, 24, "bold"))  # Reduced font size
    header.grid(row=0, column=0, sticky="w", padx=16, pady=(8,10))  # Reduced padding

    ctl_line = ctk.CTkFrame(main, fg_color="transparent")
    ctl_line.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
    ctk.CTkLabel(ctl_line, text="Min length:", font=(FONT_FAMILY, 12)).pack(side="left")
    length_entry = ctk.CTkEntry(ctl_line, width=50, font=(FONT_FAMILY, 11))  # Reduced width
    length_entry.insert(0, "1")
    length_entry.pack(side="left", padx=6)
    ctk.CTkButton(ctl_line, text="Capture once", command=lambda: capture_and_match_once(max(1, int(length_entry.get() or 1))), font=(FONT_FAMILY, 11)).pack(side="left", padx=6)
    ctk.CTkButton(ctl_line, text="🔧 Force Auto-Correct", command=force_auto_correct, font=(FONT_FAMILY, 11)).pack(side="left", padx=6)

    label_output = ctk.CTkLabel(main, text="Prompt: ", font=(FONT_FAMILY, 16))  # Reduced font size
    label_output.grid(row=2, column=0, sticky="nw", padx=16, pady=6)  # Reduced padding

    # Control buttons row
    ctrl_buttons = ctk.CTkFrame(main, fg_color="transparent")
    ctrl_buttons.grid(row=3, column=0, sticky="ew", padx=16, pady=4)
    ctk.CTkButton(ctrl_buttons, text="🗑️ Clear Used Words", command=clear_used_words, font=(FONT_FAMILY, 11)).pack(side="left", padx=(0,6))
    ctk.CTkButton(ctrl_buttons, text="🔤 Clear Alphabet", command=lambda: (typed_history.clear(), update_used_letters_display()), font=(FONT_FAMILY, 11)).pack(side="left", padx=6)

    used_letters_label = ctk.CTkLabel(main, text="Used: ", font=(FONT_FAMILY, 12))  # Reduced font size
    used_letters_label.grid(row=4, column=0, sticky="nw", padx=16, pady=4)  # Reduced padding

    words_frame = ctk.CTkFrame(main, corner_radius=10)
    words_frame.grid(row=5, column=0, sticky="nsew", padx=16, pady=8)  # Reduced padding

    status_label = ctk.CTkLabel(main, text="Status: Ready", font=(FONT_FAMILY, 11))  # Updated font
    status_label.grid(row=6, column=0, sticky="nw", padx=16, pady=8)  # Reduced padding

    # Initialize labels
    update_region_labels()
    update_used_letters_display()

    return root

# ---------------------
# Main
# ---------------------
if __name__ == "__main__":
    try:
        pyautogui.FAILSAFE = False
    except Exception:
        pass

    try:
        root = build_ui()
    except Exception as e:
        print("Failed to start UI:", e)
        sys.exit(1)

    kb_listener = pynput_keyboard.Listener(on_press=lambda k: threading.Thread(target=type_text, args=(best_current_word,), daemon=True).start() if k == pynput_keyboard.Key.f8 else None)
    kb_listener.start()

    root.mainloop()

# ---------------------
# PyInstaller Build Notes (Windows)
# ---------------------
# From project root, run:
#   pyinstaller --onefile wordbomb_ocr.py ^
#     --add-binary "vendor\tesseract\tesseract.exe;vendor\tesseract" ^
#     --add-data   "vendor\tesseract\tessdata;vendor\tesseract\tessdata"
#
# What to bundle:
#   - Required: tesseract.exe, tessdata\*.traineddata, and any DLLs alongside tesseract.exe
#   - NOT required: "doc" folder, samples, training tools
#
# Licensing:
#   - Include Apache‑2.0 license text in your distribution (e.g., LICENSE)
#   - Optional: add NOTICE.txt stating that Tesseract OCR is bundled
