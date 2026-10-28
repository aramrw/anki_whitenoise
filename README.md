# Anki White Noise & Ambient Audio Player

A lightweight Anki add-on that plays continuous looping background audio (white noise, brown noise, ambient tracks, etc.) while you use Anki, without interrupting card review audio.

## Features

- **Continuous Looping Playback**: Plays independently of Anki's card audio queue so card pronunciation/audio never cuts off your ambient sound.
- **Easy Track Management**:
  - **Import via GUI**: Use **Tools → White Noise → Settings & Select Audio...** and click **Import Audio File...**
  - **Drop into Folder**: Drop `.mp3`, `.wav`, `.ogg`, `.flac`, `.m4a`, `.aac`, or `.opus` files directly into the add-on's `user_files` directory.
- **Volume & Playback Modes**:
  - Adjust volume (`0%` – `100%`) directly in the settings dialog.
  - Choose between **always playing** while Anki is open or **only while reviewing cards**.
  - Quick enable/disable toggle under **Tools → White Noise → Enable White Noise**.

## Installation

1. Open Anki and go to **Tools → Add-ons → Open Add-ons Folder...**
2. Clone this repository into your `addons21` folder:
   ```bash
   git clone https://github.com/aramrw/anki_whitenoise.git whitenoise_player
   ```
3. Restart Anki.
4. Go to **Tools → White Noise → Settings & Select Audio...** to import and select your audio file.
