import pytesseract
import pyautogui
import time
from PIL import Image
import tkinter as tk
from tkinter import messagebox, filedialog
import threading
from pynput import mouse, keyboard as pynput_keyboard
import os

pytesseract.pytesseract.tesseract_cmd = r'/opt/homebrew/bin/tesseract'

selected_region = {"x1": None, "y1": None, "x2": None, "y2": None}
word_list = []
typed_history = set()
used_words = set()
best_current_word = ""
ocr_running = False
save_images = True

def load_dictionary():
    global word_list
    path = filedialog.askopenfilename(title="select a dictionary (.txt)", filetypes=[("Text Files", "*.txt")])
    if not path:
        return
    with open(path, 'r', encoding='utf-8') as file:
        word_list = [line.strip().upper() for line in file if line.strip()]
    label_dict.config(text=f"loaded {len(word_list)} words.")

def type_text(text):
    global typed_history, used_words
    typed_history.update(set(text.upper()))
    used_words.add(text.upper())
    if len(typed_history) >= 26:
        typed_history.clear()
    update_used_letters_display()
    time.sleep(0.2)
    pyautogui.write(text, interval=0.01)
    pyautogui.press('enter')

def update_used_letters_display():
    letters = ''.join(sorted(typed_history))
    used_letters_label.config(text=f"used: {letters}")

def score_word(word, used_letters):
    unique = set(word)
    bonus = len(unique - used_letters)
    return (bonus, len(unique))

def capture_and_match(region, output_label, word_frame, min_length):
    global best_current_word
    try:
        x1, y1, x2, y2 = region
        x, y = int(min(x1, x2)), int(min(y1, y2))
        w, h = int(abs(x2 - x1)), int(abs(y2 - y1))
        screenshot = pyautogui.screenshot(region=(x, y, w, h)).convert('L')
        screenshot = screenshot.resize((int(w * 2), int(h * 2)), Image.BICUBIC)
        screenshot = screenshot.point(lambda p: 255 if p > 180 else 0)

        if save_images:
            os.makedirs("ocr_images", exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            screenshot.save(f"ocr_images/ocr_{timestamp}.png")

        config = "--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        root_text = pytesseract.image_to_string(screenshot, config=config).strip().upper()
        if not root_text:
            update_output("no prompt detected.", [], word_frame)
            return
        matches = [word for word in word_list if root_text in word and len(word) >= min_length and word not in used_words]
        if matches:
            matches.sort(key=lambda w: score_word(w, typed_history), reverse=True)
            best_word = matches[0]
            best_current_word = best_word
            update_output(f"dtc: {root_text}", [best_word], word_frame)
        else:
            best_current_word = ""
            update_output(f"dtc: {root_text}", [], word_frame)
    except Exception as e:
        update_output(f"err: {e}", [], word_frame)

def update_output(prompt_text, word_matches, word_frame):
    for widget in word_frame.winfo_children():
        widget.destroy()
    label_output.config(text=prompt_text)
    if word_matches:
        btn = tk.Button(word_frame, text=word_matches[0], width=30,
                        command=lambda w=word_matches[0]: threading.Thread(target=type_text, args=(w,)).start())
        btn.pack(pady=2)

def start_live_ocr():
    global ocr_running
    if None in selected_region.values():
        messagebox.showerror("error", "ocr region is not set.")
        return
    ocr_running = True
    def loop():
        while ocr_running:
            region = (
                selected_region["x1"],
                selected_region["y1"],
                selected_region["x2"],
                selected_region["y2"]
            )
            min_length = int(length_entry.get()) if length_entry.get().isdigit() else 1
            capture_and_match(region, label_output, words_frame, min_length)
            time.sleep(0.1)
    threading.Thread(target=loop, daemon=True).start()

def stop_live_ocr():
    global ocr_running
    ocr_running = False

def clear_used_words():
    used_words.clear()
    messagebox.showinfo("cleared", "used word history cleared.")

def toggle_image_saving():
    global save_images
    save_images = not save_images
    save_img_button.config(text=f"save images: {'on' if save_images else 'off'}")

def on_f8_press(key):
    if key == pynput_keyboard.Key.f8 and best_current_word:
        threading.Thread(target=type_text, args=(best_current_word,)).start()

listener = pynput_keyboard.Listener(on_press=on_f8_press)
listener.start()

def run_ui():
    def on_select_region():
        messagebox.showinfo("region select", "click top left and bottom right of the ocr area.")
        root.withdraw()
        threading.Thread(target=get_mouse_clicks).start()

    def get_mouse_clicks():
        coords = []
        def on_click(x, y, button, pressed):
            if pressed:
                coords.append((x, y))
                if len(coords) == 2:
                    selected_region["x1"], selected_region["y1"] = coords[0]
                    selected_region["x2"], selected_region["y2"] = coords[1]
                    update_region_label()
                    listener_mouse.stop()
                    root.deiconify()
        global listener_mouse
        listener_mouse = mouse.Listener(on_click=on_click)
        listener_mouse.start()
        listener_mouse.join()

    def update_region_label():
        coords = f'{selected_region["x1"]},{selected_region["y1"]} to {selected_region["x2"]},{selected_region["y2"]}'
        label_region.config(text=f"selected region: {coords}")

    def on_capture():
        try:
            region = (
                selected_region["x1"],
                selected_region["y1"],
                selected_region["x2"],
                selected_region["y2"]
            )
            if None in region:
                raise ValueError("region not selected")
            min_length = int(length_entry.get()) if length_entry.get().isdigit() else 1
            threading.Thread(target=capture_and_match, args=(region, label_output, words_frame, min_length)).start()
        except Exception as e:
            messagebox.showerror("error", str(e))

    def on_type():
        if best_current_word:
            threading.Thread(target=type_text, args=(best_current_word,)).start()
        else:
            messagebox.showinfo("no word", "no suggested word to type")

    global root, label_output, label_region, label_dict, words_frame, length_entry, used_letters_label, save_img_button
    root = tk.Tk()
    root.title("wordbomb ocr tool")
    root.attributes("-topmost", True)

    window_width = 600
    window_height = 850
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x_position = (screen_width - window_width) // 2
    y_position = (screen_height - window_height) // 2
    root.geometry(f"{window_width}x{window_height}+{x_position}+{y_position}")

    frame = tk.Frame(root)
    frame.pack(pady=10)

    tk.Button(frame, text="select ocr region", command=on_select_region, width=30).pack(pady=5)
    label_region = tk.Label(frame, text="selected region: not set", fg="green", font=("Arial", 10))
    label_region.pack(pady=5)

    tk.Button(frame, text="load dictionary", command=load_dictionary, width=30).pack(pady=5)
    label_dict = tk.Label(frame, text="no dictionary loaded", fg="purple", font=("Arial", 10))
    label_dict.pack(pady=5)

    tk.Label(frame, text="min word length:", font=("Arial", 10)).pack(pady=5)
    length_entry = tk.Entry(frame, width=10)
    length_entry.insert(0, "1")
    length_entry.pack(pady=5)

    save_img_button = tk.Button(frame, text="save images: on", command=toggle_image_saving, width=30)
    save_img_button.pack(pady=5)

    tk.Button(frame, text="capture ocr", command=on_capture, width=30).pack(pady=5)
    tk.Button(frame, text="type suggested word", command=on_type, width=30).pack(pady=5)
    tk.Button(frame, text="start live ocr", command=start_live_ocr, width=30).pack(pady=5)
    tk.Button(frame, text="stop live ocr", command=stop_live_ocr, width=30).pack(pady=5)
    tk.Button(frame, text="clear used word history", command=clear_used_words, width=30).pack(pady=5)
    tk.Button(frame, text="clear alphabet", command=lambda: (typed_history.clear(), update_used_letters_display()), width=30).pack(pady=5)

    label_output = tk.Label(frame, text="generated: ", fg="blue", font=("Arial", 12))
    label_output.pack(pady=10)

    used_letters_label = tk.Label(frame, text="used: ", fg="darkblue", font=("Courier", 10))
    used_letters_label.pack(pady=5)

    words_frame = tk.Frame(frame)
    words_frame.pack(pady=5)

    root.mainloop()

run_ui()
