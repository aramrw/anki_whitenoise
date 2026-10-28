from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from aqt import gui_hooks, mw
from aqt.qt import (
    QAction,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    Qt,
    QUrl,
    QVBoxLayout,
)
from aqt.utils import openFolder, showInfo, tooltip

try:
    from aqt.qt import QAudioOutput, QMediaPlayer
    HAS_QT_MEDIA = True
except ImportError:
    try:
        from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
        HAS_QT_MEDIA = True
    except ImportError:
        HAS_QT_MEDIA = False

ADDON_DIR = Path(__file__).parent
USER_FILES_DIR = ADDON_DIR / "user_files"
USER_FILES_DIR.mkdir(exist_ok=True)

SUPPORTED_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus", ".mp4"}


class WhiteNoisePlayer:
    def __init__(self) -> None:
        self.qt_player: Optional[QMediaPlayer] = None
        self.qt_audio_output: Optional[QAudioOutput] = None
        self.proc: Optional[subprocess.Popen] = None
        self.current_path: Optional[Path] = None
        self._is_playing: bool = False

        if HAS_QT_MEDIA:
            try:
                self.qt_player = QMediaPlayer()
                self.qt_audio_output = QAudioOutput()
                self.qt_player.setAudioOutput(self.qt_audio_output)
                # Loop infinitely in Qt6
                if hasattr(QMediaPlayer, "Loops"):
                    self.qt_player.setLoops(QMediaPlayer.Loops.Infinite)
                else:
                    self.qt_player.mediaStatusChanged.connect(self._on_media_status_changed)
            except Exception:
                self.qt_player = None
                self.qt_audio_output = None

    def _on_media_status_changed(self, status) -> None:
        if self.qt_player and hasattr(QMediaPlayer, "MediaStatus"):
            if status == QMediaPlayer.MediaStatus.EndOfMedia and self._is_playing:
                self.qt_player.play()

    def get_config(self) -> dict:
        cfg = mw.addonManager.getConfig(__name__) or {}
        return {
            "selected_file": cfg.get("selected_file", ""),
            "enabled": bool(cfg.get("enabled", True)),
            "volume": int(cfg.get("volume", 50)),
            "only_during_reviews": bool(cfg.get("only_during_reviews", False)),
        }

    def save_config(self, cfg: dict) -> None:
        mw.addonManager.writeConfig(__name__, cfg)

    def list_audio_files(self) -> list[str]:
        files = []
        for folder in (USER_FILES_DIR, ADDON_DIR):
            if folder.exists():
                for p in sorted(folder.iterdir()):
                    if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
                        if p.name not in files:
                            files.append(p.name)
        return files

    def resolve_audio_path(self, filename: str) -> Optional[Path]:
        if not filename:
            return None
        for folder in (USER_FILES_DIR, ADDON_DIR):
            candidate = folder / filename
            if candidate.is_file():
                return candidate
        direct = Path(filename)
        if direct.is_file():
            return direct
        return None

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        if self.qt_audio_output is not None:
            self.qt_audio_output.setVolume(volume / 100.0)
        elif self._is_playing and self.current_path:
            # Restart subprocess player with updated volume
            self._start_subprocess(self.current_path, volume)

    def play_file(self, path: Path, volume: int) -> None:
        self.stop()
        self.current_path = path
        self._is_playing = True

        if self.qt_player is not None and self.qt_audio_output is not None:
            self.qt_audio_output.setVolume(max(0, min(100, volume)) / 100.0)
            self.qt_player.setSource(QUrl.fromLocalFile(str(path)))
            self.qt_player.play()
        else:
            self._start_subprocess(path, volume)

    def _start_subprocess(self, path: Path, volume: int) -> None:
        self._stop_subprocess()
        mpv_bin = shutil.which("mpv") or "/opt/homebrew/bin/mpv"
        ffplay_bin = shutil.which("ffplay") or "/opt/homebrew/bin/ffplay"
        afplay_bin = shutil.which("afplay") or "/usr/bin/afplay"

        if os.path.exists(mpv_bin):
            cmd = [
                mpv_bin,
                "--no-video",
                "--loop-file=inf",
                f"--volume={volume}",
                "--really-quiet",
                str(path),
            ]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.path.exists(ffplay_bin):
            cmd = [
                ffplay_bin,
                "-nodisp",
                "-loop",
                "0",
                "-volume",
                str(volume),
                "-loglevel",
                "quiet",
                str(path),
            ]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.path.exists(afplay_bin):
            # Loop afplay in a subshell
            vol_float = max(0.0, min(1.0, volume / 100.0))
            escaped = str(path).replace("'", "'\\''")
            cmd = ["/bin/sh", "-c", f"while true; do '{afplay_bin}' -v {vol_float} '{escaped}' || break; done"]
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _stop_subprocess(self) -> None:
        if self.proc is not None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=1.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

    def stop(self) -> None:
        self._is_playing = False
        if self.qt_player is not None:
            self.qt_player.stop()
        self._stop_subprocess()

    def sync_playback_state(self, current_state: Optional[str] = None) -> None:
        cfg = self.get_config()
        if not cfg["enabled"]:
            self.stop()
            return

        selected = cfg["selected_file"]
        files = self.list_audio_files()
        if not selected and files:
            selected = files[0]
            cfg["selected_file"] = selected
            self.save_config(cfg)

        path = self.resolve_audio_path(selected)
        if not path:
            self.stop()
            return

        state = current_state or getattr(mw, "state", None)
        if cfg["only_during_reviews"] and state != "review":
            self.stop()
            return

        if not self._is_playing or self.current_path != path:
            self.play_file(path, cfg["volume"])
        else:
            self.set_volume(cfg["volume"])


player: Optional[WhiteNoisePlayer] = None
toggle_action: Optional[QAction] = None


class WhiteNoiseDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent or mw)
        self.setWindowTitle("White Noise Player")
        self.setMinimumWidth(400)
        self._setup_ui()
        self._load_from_config()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Enable checkbox
        self.enabled_cb = QCheckBox("Enable White Noise (Always Playing)")
        self.enabled_cb.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.enabled_cb)

        # Only during reviews checkbox
        self.reviews_only_cb = QCheckBox("Play only while reviewing cards")
        self.reviews_only_cb.stateChanged.connect(self._on_settings_changed)
        layout.addWidget(self.reviews_only_cb)

        # Track selector row
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Audio Track:"))
        self.file_combo = QComboBox()
        self.file_combo.currentTextChanged.connect(self._on_file_selected)
        file_layout.addWidget(self.file_combo, stretch=1)
        layout.addLayout(file_layout)

        # Buttons for adding files or opening the folder
        btn_layout = QHBoxLayout()
        self.add_file_btn = QPushButton("Import Audio File...")
        self.add_file_btn.clicked.connect(self._import_audio_file)
        btn_layout.addWidget(self.add_file_btn)

        self.open_folder_btn = QPushButton("Open Audio Folder")
        self.open_folder_btn.clicked.connect(self._open_audio_folder)
        btn_layout.addWidget(self.open_folder_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_files)
        btn_layout.addWidget(self.refresh_btn)
        layout.addLayout(btn_layout)

        # Volume slider row
        vol_layout = QHBoxLayout()
        vol_layout.addWidget(QLabel("Volume:"))
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        vol_layout.addWidget(self.vol_slider, stretch=1)
        self.vol_label = QLabel("50%")
        self.vol_label.setMinimumWidth(40)
        vol_layout.addWidget(self.vol_label)
        layout.addLayout(vol_layout)

        # Hint label
        hint = QLabel(
            f"<small>Drop audio files (.mp3, .wav, .ogg, .flac, .m4a) into:<br>"
            f"<code>{USER_FILES_DIR}</code></small>"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _load_from_config(self) -> None:
        if not player:
            return
        cfg = player.get_config()
        self.enabled_cb.blockSignals(True)
        self.reviews_only_cb.blockSignals(True)
        self.vol_slider.blockSignals(True)

        self.enabled_cb.setChecked(cfg["enabled"])
        self.reviews_only_cb.setChecked(cfg["only_during_reviews"])
        self.vol_slider.setValue(cfg["volume"])
        self.vol_label.setText(f"{cfg['volume']}%")

        self.enabled_cb.blockSignals(False)
        self.reviews_only_cb.blockSignals(False)
        self.vol_slider.blockSignals(False)

        self._refresh_files(selected_override=cfg["selected_file"])

    def _refresh_files(self, selected_override: Optional[str] = None) -> None:
        if not player:
            return
        current = selected_override if isinstance(selected_override, str) else self.file_combo.currentText()
        files = player.list_audio_files()

        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        if files:
            self.file_combo.addItems(files)
            if current in files:
                self.file_combo.setCurrentText(current)
            else:
                self.file_combo.setCurrentIndex(0)
        self.file_combo.blockSignals(False)

        if files and self.file_combo.currentText() != current:
            self._on_file_selected(self.file_combo.currentText())

    def _import_audio_file(self) -> None:
        file_filter = "Audio Files (*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.opus *.mp4);;All Files (*)"
        path_str, _ = QFileDialog.getOpenFileName(self, "Select Audio File", "", file_filter)
        if not path_str:
            return
        src = Path(path_str)
        if not src.is_file():
            return
        USER_FILES_DIR.mkdir(exist_ok=True)
        dest = USER_FILES_DIR / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        self._refresh_files(selected_override=dest.name)
        self._on_file_selected(dest.name)
        tooltip(f"Imported {dest.name}")

    def _open_audio_folder(self) -> None:
        USER_FILES_DIR.mkdir(exist_ok=True)
        openFolder(str(USER_FILES_DIR))

    def _on_file_selected(self, filename: str) -> None:
        if not player:
            return
        cfg = player.get_config()
        cfg["selected_file"] = filename
        player.save_config(cfg)
        player.sync_playback_state()
        update_menu_state()

    def _on_settings_changed(self) -> None:
        if not player:
            return
        cfg = player.get_config()
        cfg["enabled"] = self.enabled_cb.isChecked()
        cfg["only_during_reviews"] = self.reviews_only_cb.isChecked()
        player.save_config(cfg)
        player.sync_playback_state()
        update_menu_state()

    def _on_volume_changed(self, value: int) -> None:
        self.vol_label.setText(f"{value}%")
        if not player:
            return
        cfg = player.get_config()
        cfg["volume"] = value
        player.save_config(cfg)
        player.set_volume(value)


def open_settings_dialog() -> None:
    dlg = WhiteNoiseDialog(mw)
    dlg.exec()


def toggle_playback() -> None:
    if not player:
        return
    cfg = player.get_config()
    cfg["enabled"] = not cfg["enabled"]
    player.save_config(cfg)
    player.sync_playback_state()
    update_menu_state()
    status = "ON" if cfg["enabled"] else "OFF"
    tooltip(f"White Noise: {status}")


def update_menu_state() -> None:
    if not player or not toggle_action:
        return
    cfg = player.get_config()
    toggle_action.setChecked(cfg["enabled"])


def setup_menu() -> None:
    global toggle_action
    menu = QMenu("White Noise", mw)
    mw.form.menuTools.addMenu(menu)

    toggle_action = QAction("Enable White Noise", mw)
    toggle_action.setCheckable(True)
    toggle_action.triggered.connect(toggle_playback)
    menu.addAction(toggle_action)

    settings_action = QAction("Settings && Select Audio...", mw)
    settings_action.triggered.connect(open_settings_dialog)
    menu.addAction(settings_action)

    folder_action = QAction("Open Audio Folder", mw)
    folder_action.triggered.connect(lambda: openFolder(str(USER_FILES_DIR)))
    menu.addAction(folder_action)

    # Also register as the addon's config action in Tools -> Add-ons
    mw.addonManager.setConfigAction(__name__, open_settings_dialog)
    update_menu_state()


def on_profile_did_open() -> None:
    global player
    if player is None:
        player = WhiteNoisePlayer()
    update_menu_state()
    player.sync_playback_state()


def on_state_did_change(new_state: str, old_state: str) -> None:
    if player is not None:
        player.sync_playback_state(current_state=new_state)


def on_profile_will_close() -> None:
    if player is not None:
        player.stop()


gui_hooks.main_window_did_init.append(setup_menu)
gui_hooks.profile_did_open.append(on_profile_did_open)
gui_hooks.state_did_change.append(on_state_did_change)
gui_hooks.profile_will_close.append(on_profile_will_close)
