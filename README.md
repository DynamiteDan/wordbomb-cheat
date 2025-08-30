# WordBomb OCR Assistant

*A Python + Tesseract OCR tool for automating word detection in the game WordBomb*

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Issues](https://img.shields.io/github/issues/DynamiteDan/wordbomb-cheat)](https://github.com/DynamiteDan/wordbomb-cheat/issues)
[![Stars](https://img.shields.io/github/stars/DynamiteDan/wordbomb-cheat?style=social)](https://github.com/DynamiteDan/wordbomb-cheat/stargazers)

## Overview

This project is a WordBomb cheat that uses **Tesseract OCR** to detect the letter prompts in-game and automatically suggest words from a dictionary. It can also auto-type the best match with a single key press (`F8`).

It was built as a **personal passion project** and is not guaranteed to be actively maintained. The code is open-source, so you are free to fork and extend it.

## Features

* Dual OCR regions (Region A required, Region B optional) to support the Roblox version
* Optimized Tesseract OCR pipeline (custom configs + character correction for I/L confusion)
* Fast dictionary matching using 2- and 3-gram indexing
* Auto-typing of best match via `F8` hotkey
* Modern CustomTkinter UI with status indicators
* Custom dictionary loading (TXT word lists)
* Optional image saving for debugging OCR results

## Installation

1. Install **Python 3.10+** and **pip**.
2. Clone this repository:

   ```bash
   git clone https://github.com/DynamiteDan/wordbomb-cheat.git
   cd wordbomb-cheat
   ```
3. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```
4. ~~Download and install **Tesseract OCR**:

   * Windows builds: [UB Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki)
   * Either add `tesseract.exe` to your PATH or place it in `vendor/tesseract/`.~~

## FORTUNATELY THIS STEP IS NO LONGER REQUIRED, JUST RUN THE PYTHON FILE ON AN IDE OF YOUR CHOICE

## Usage

Run:

```bash
python app.py
```

### Controls:

* Select OCR Region A (required)
* Select OCR Region B (optional)
* Load dictionary → choose a `.txt` wordlist
* Start Live OCR → continuously detect prompts
* Press **F8** → auto-type the current best word

## Notes

* Bundles **Tesseract OCR (Apache License 2.0)** — copyright © Google and contributors.
* Currently requires you to supply your own dictionary (`.txt`). A sample is included.
* A compiled `.exe` release is planned so Tesseract is bundled automatically.

## Disclaimer

This was created as a **passion project**.

* It is not intended to be used to ruin other players’ experiences in real games.
* Use responsibly — I am not responsible for how you choose to use it.

## Roadmap

* [x] Cleaner UI (Tkinter with dark theme)
* [x] Improved OCR accuracy (dual region, retries, correction)
* [ ] Bundle Tesseract into `.exe` with PyInstaller
* [ ] Add packaged releases with wordlists

## License

This project bundles **Tesseract OCR**, licensed under the **Apache License 2.0**.
Please see the [LICENSE](LICENSE.md) file for details.
