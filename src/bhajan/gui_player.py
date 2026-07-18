"""GUI Karaoke Player — plays audio with synchronized lyric lines.

Uses pygame for audio and tkinter for a scrollable lyric list: the active
line is highlighted and the view auto-scrolls to keep it near the vertical
center while playing.

Usage::

    bhajan "<url>" --gui
"""

from __future__ import annotations

import logging
import time
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

from bhajan.logger import StageLogger
from bhajan.stages.transcription_base import Segment, Transcript

log = logging.getLogger("bhajan")
stage = StageLogger(log, "gui")

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class KaraokeGUI:
    """Tkinter player: scrollable lyrics + line sync + pygame audio."""

    def __init__(
        self,
        audio_path: Path,
        transcript: Transcript,
        title: str = "Karaoke Player",
    ) -> None:
        if not PYGAME_AVAILABLE:
            raise RuntimeError(
                "pygame is required for GUI playback.\n"
                "Install it with: uv add pygame-ce  (or pip install pygame)"
            )

        self.audio_path = audio_path
        self.transcript = transcript
        self.segments = [s for s in transcript.segments if s.words]
        self.title = title

        self.line_labels: list[tk.Label] = []
        self.current_line_index = -1

        self._layout_signature: tuple[int, int, int, int] | None = None

        self.is_playing = False
        self.is_paused = False
        self.audio_loaded = False
        self.duration = 0.0

        self.update_interval = 50

        self._init_pygame()
        self._build_ui()

    def _init_pygame(self) -> None:
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)

    def _setup_styles(self) -> None:
        self.title_font = tkfont.Font(family="Segoe UI", size=20, weight="bold")
        self.lyrics_line_font = tkfont.Font(family="Segoe UI", size=16)
        self.active_line_font = tkfont.Font(family="Segoe UI", size=18, weight="bold")
        self.button_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.small_font = tkfont.Font(family="Segoe UI", size=10)

    def _compute_text_metrics(self) -> tuple[int, int, int, int, int] | None:
        """Return (lyrics_wrap_px, lyrics_pt, active_pt, title_wrap_px, title_pt) or None if not laid out yet."""
        self.root.update_idletasks()
        screen = max(1, int(self.root.winfo_screenwidth()))
        cap = max(240, screen // 2)

        cw = int(self.lyrics_canvas.winfo_width())
        if cw < 16:
            return None

        inner_pad = 28
        lyrics_wrap = min(max(100, cw - inner_pad), cap)
        lyrics_pt = max(12, min(44, int(lyrics_wrap * 0.028)))
        active_pt = max(13, min(50, int(lyrics_pt * 1.14)))

        root_w = max(200, int(self.root.winfo_width()))
        title_wrap = min(max(160, root_w - 48), cap)
        title_pt = max(14, min(28, int(title_wrap * 0.036)))

        return lyrics_wrap, lyrics_pt, active_pt, title_wrap, title_pt

    def _apply_responsive_layout(self, _event: object | None = None) -> None:
        m = self._compute_text_metrics()
        if m is None:
            return
        lyrics_wrap, lyrics_pt, active_pt, title_wrap, title_pt = m
        sig = (lyrics_wrap, lyrics_pt, title_wrap, title_pt)
        if sig == self._layout_signature:
            return
        self._layout_signature = sig

        self.title_font.configure(size=title_pt)
        self.lyrics_line_font.configure(size=lyrics_pt)
        self.active_line_font.configure(size=active_pt)

        self.title_label.configure(wraplength=title_wrap)

        for lbl in self.line_labels:
            lbl.configure(wraplength=lyrics_wrap)

        self.lyrics_inner.update_idletasks()
        self._refresh_scrollregion()

        active = self.current_line_index
        if active >= 0:
            self._set_line_styles(active)

    def _build_ui(self) -> None:
        self.root = tk.Tk()
        self.root.title(f"bhajan — {self.title}")
        self.root.geometry("720x640")
        self.root.minsize(480, 400)
        self.root.configure(bg="#0c0c1e")

        self._setup_styles()

        main_frame = tk.Frame(self.root, bg="#0c0c1e")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        self.title_label = tk.Label(
            main_frame,
            text=self.title,
            font=self.title_font,
            bg="#0c0c1e",
            fg="#ffffff",
            wraplength=680,
            justify=tk.CENTER,
            anchor="center",
        )
        self.title_label.pack(pady=(0, 12), fill=tk.X)

        lyrics_frame = tk.Frame(main_frame, bg="#0c0c1e")
        lyrics_frame.pack(fill=tk.BOTH, expand=True, pady=6)

        self.lyrics_canvas = tk.Canvas(
            lyrics_frame,
            bg="#12122a",
            highlightthickness=1,
            highlightbackground="#2a2a44",
            bd=0,
        )
        self.lyrics_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(lyrics_frame, command=self.lyrics_canvas.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.lyrics_canvas.configure(yscrollcommand=scrollbar.set)

        self.lyrics_inner = tk.Frame(self.lyrics_canvas, bg="#12122a")
        self._inner_canvas_id = self.lyrics_canvas.create_window(
            (0, 0),
            window=self.lyrics_inner,
            anchor="nw",
        )

        self._build_lyrics_display()

        self.lyrics_canvas.bind("<Configure>", self._on_canvas_configure)
        self.root.bind("<Configure>", self._on_root_configure)
        lyrics_frame.bind("<Enter>", self._lyrics_enter)
        lyrics_frame.bind("<Leave>", self._lyrics_leave)

        progress_frame = tk.Frame(main_frame, bg="#0c0c1e")
        progress_frame.pack(fill=tk.X, pady=(12, 6))

        time_frame = tk.Frame(progress_frame, bg="#0c0c1e")
        time_frame.pack(fill=tk.X)

        self.current_time_label = tk.Label(
            time_frame,
            text="0:00",
            font=self.small_font,
            bg="#0c0c1e",
            fg="#888888",
        )
        self.current_time_label.pack(side=tk.LEFT)

        self.total_time_label = tk.Label(
            time_frame,
            text="0:00",
            font=self.small_font,
            bg="#0c0c1e",
            fg="#888888",
        )
        self.total_time_label.pack(side=tk.RIGHT)

        self.progress_canvas = tk.Canvas(
            progress_frame,
            height=8,
            bg="#333333",
            highlightthickness=0,
            bd=0,
        )
        self.progress_canvas.pack(fill=tk.X, pady=6)

        self.progress_fill = self.progress_canvas.create_rectangle(
            0, 0, 0, 8, fill="#00d4d4", outline=""
        )
        self.progress_canvas.bind("<Button-1>", self._on_progress_click)

        controls_frame = tk.Frame(main_frame, bg="#0c0c1e")
        controls_frame.pack(pady=8)

        self.play_btn = tk.Button(
            controls_frame,
            text="▶ Play",
            command=self._toggle_playback,
            font=self.button_font,
            bg="#00d4d4",
            fg="#000000",
            activebackground="#00aaaa",
            activeforeground="#000000",
            bd=0,
            padx=24,
            pady=8,
            cursor="hand2",
        )
        self.play_btn.pack(side=tk.LEFT, padx=4)

        restart_btn = tk.Button(
            controls_frame,
            text="↺ Restart",
            command=self._restart,
            font=self.button_font,
            bg="#333333",
            fg="#ffffff",
            activebackground="#444444",
            bd=0,
            padx=16,
            pady=8,
            cursor="hand2",
        )
        restart_btn.pack(side=tk.LEFT, padx=4)

        seek_back_btn = tk.Button(
            controls_frame,
            text="⏮ −10s",
            command=lambda: self._seek_relative(-10),
            font=self.button_font,
            bg="#333333",
            fg="#ffffff",
            activebackground="#444444",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        seek_back_btn.pack(side=tk.LEFT, padx=4)

        seek_fwd_btn = tk.Button(
            controls_frame,
            text="+10s ⏭",
            command=lambda: self._seek_relative(10),
            font=self.button_font,
            bg="#333333",
            fg="#ffffff",
            activebackground="#444444",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
        )
        seek_fwd_btn.pack(side=tk.LEFT, padx=4)

        self.status_label = tk.Label(
            main_frame,
            text="Scroll lyrics with the mouse wheel · Space = play/pause",
            font=self.small_font,
            bg="#0c0c1e",
            fg="#888888",
        )
        self.status_label.pack(pady=6)

        self.root.bind("<space>", lambda e: self._toggle_playback())
        self.root.bind("<Left>", lambda e: self._seek_relative(-5))
        self.root.bind("<Right>", lambda e: self._seek_relative(5))
        self.root.bind("<Escape>", lambda e: self._quit())
        self.root.bind("<q>", lambda e: self._quit())

        self.root.protocol("WM_DELETE_WINDOW", self._quit)

        self._load_audio()

        self.root.after_idle(self._apply_responsive_layout)

    def _build_lyrics_display(self) -> None:
        self.line_labels.clear()
        wrap = max(320, self.lyrics_canvas.winfo_width() or 640)

        for seg in self.segments:
            text = seg.text.strip() or "·"
            lbl = tk.Label(
                self.lyrics_inner,
                text=text,
                font=self.lyrics_line_font,
                bg="#12122a",
                fg="#5a5a72",
                wraplength=wrap,
                justify=tk.CENTER,
                anchor="center",
                padx=12,
                pady=6,
            )
            lbl.pack(fill=tk.X)
            self.line_labels.append(lbl)

        self.lyrics_inner.update_idletasks()
        self._refresh_scrollregion()

    def _on_canvas_configure(self, event: tk.Event) -> None:
        inner_w = max(1, event.width - 4)
        self.lyrics_canvas.itemconfigure(self._inner_canvas_id, width=inner_w)
        self._apply_responsive_layout()

    def _on_root_configure(self, _event: tk.Event) -> None:
        self._apply_responsive_layout()

    def _refresh_scrollregion(self) -> None:
        self.lyrics_inner.update_idletasks()
        bbox = self.lyrics_canvas.bbox("all")
        if bbox:
            self.lyrics_canvas.configure(scrollregion=bbox)

    def _lyrics_enter(self, _event: tk.Event) -> None:
        self.lyrics_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _lyrics_leave(self, _event: tk.Event) -> None:
        self.lyrics_canvas.unbind_all("<MouseWheel>")

    def _on_mousewheel(self, event: tk.Event) -> None:
        if getattr(event, "delta", 0):
            self.lyrics_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _line_index_at_time(self, t: float) -> int:
        if not self.segments:
            return -1
        idx = 0
        for i, seg in enumerate(self.segments):
            if seg.start <= t:
                idx = i
        return idx

    def _set_line_styles(self, active_idx: int) -> None:
        for i, lbl in enumerate(self.line_labels):
            if i == active_idx:
                lbl.configure(fg="#00ffff", font=self.active_line_font)
            elif active_idx >= 0 and i < active_idx:
                lbl.configure(fg="#7a7a8e", font=self.lyrics_line_font)
            else:
                lbl.configure(fg="#5a5a72", font=self.lyrics_line_font)

    def _scroll_active_line_to_center(self, index: int) -> None:
        if index < 0 or index >= len(self.line_labels):
            return
        self.lyrics_canvas.update_idletasks()
        bbox = self.lyrics_canvas.bbox("all")
        if not bbox:
            return
        _x1, _y1, _x2, total_h = bbox
        ch = self.lyrics_canvas.winfo_height()
        if total_h <= ch or ch < 10:
            return

        w = self.line_labels[index]
        y_top = w.winfo_y()
        h_line = w.winfo_height()
        center_y = y_top + h_line / 2

        target_top = center_y - ch / 2
        max_top = max(0.0, float(total_h - ch))
        target_top = max(0.0, min(target_top, max_top))
        fraction = target_top / float(total_h) if total_h else 0.0
        self.lyrics_canvas.yview_moveto(max(0.0, min(1.0, fraction)))

    def _load_audio(self) -> None:
        try:
            pygame.mixer.music.load(str(self.audio_path))
            sound = pygame.mixer.Sound(str(self.audio_path))
            self.duration = sound.get_length()
            self.total_time_label.configure(text=self._format_time(self.duration))
            self.audio_loaded = True
            stage.info("Audio loaded: %.1f seconds", self.duration)
        except Exception as e:
            self.audio_loaded = False
            stage.error("Failed to load audio: %s", e)
            self.status_label.configure(text=f"Error loading audio: {e}", fg="#ff4444")
            self.play_btn.configure(state=tk.DISABLED)

    def _toggle_playback(self) -> None:
        if not self.is_playing:
            self._start_playback()
        elif self.is_paused:
            self._resume_playback()
        else:
            self._pause_playback()

    def _start_playback(self) -> None:
        if not self.audio_loaded:
            self.status_label.configure(
                text="Audio is not loaded; see the terminal for details.",
                fg="#ff4444",
            )
            return
        pygame.mixer.music.play(start=0.0)
        self.is_playing = True
        self.is_paused = False
        self.start_time = time.time()
        self.pause_offset = 0.0
        self.play_btn.configure(text="⏸ Pause")
        self.status_label.configure(text="Playing…")
        self._schedule_update()

    def _pause_playback(self) -> None:
        pygame.mixer.music.pause()
        self.is_paused = True
        self.pause_time = time.time()
        self.play_btn.configure(text="▶ Resume")
        self.status_label.configure(text="Paused")

    def _resume_playback(self) -> None:
        pygame.mixer.music.unpause()
        self.is_paused = False
        self.pause_offset += time.time() - self.pause_time
        self.play_btn.configure(text="⏸ Pause")
        self.status_label.configure(text="Playing…")

    def _restart(self) -> None:
        pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        self.current_line_index = -1
        self._set_line_styles(-1)
        self.play_btn.configure(text="▶ Play")
        self.status_label.configure(text="Press Play to start")
        self._update_progress_bar(0)
        self._update_time_display(0)
        self.lyrics_canvas.yview_moveto(0)

    def _seek_relative(self, seconds: float) -> None:
        if not self.is_playing:
            return

        current_pos = self._get_current_time()
        new_pos = max(0, min(self.duration, current_pos + seconds))

        was_paused = self.is_paused
        pygame.mixer.music.play(start=new_pos)
        if was_paused:
            pygame.mixer.music.pause()

        self.start_time = time.time() - new_pos
        self.pause_offset = 0.0

        idx = self._line_index_at_time(new_pos)
        if idx != self.current_line_index:
            self.current_line_index = idx
        self._set_line_styles(idx)
        self._scroll_active_line_to_center(idx)

    def _on_progress_click(self, event: tk.Event) -> None:
        if self.duration <= 0:
            return

        width = self.progress_canvas.winfo_width()
        click_x = event.x
        ratio = max(0, min(1, click_x / max(1, width)))
        new_pos = ratio * self.duration

        was_paused = self.is_paused
        if not self.is_playing:
            pygame.mixer.music.play(start=new_pos)
            self.is_playing = True
            self.is_paused = False
            self.start_time = time.time() - new_pos
            self.pause_offset = 0.0
            self.play_btn.configure(text="⏸ Pause")
            self._schedule_update()
        else:
            pygame.mixer.music.play(start=new_pos)
            if was_paused:
                pygame.mixer.music.pause()
            self.start_time = time.time() - new_pos
            self.pause_offset = 0.0

        idx = self._line_index_at_time(new_pos)
        self.current_line_index = idx
        self._set_line_styles(idx)
        self._scroll_active_line_to_center(idx)

    def _get_current_time(self) -> float:
        if not self.is_playing:
            return 0.0
        if self.is_paused:
            return self.pause_time - self.start_time - self.pause_offset
        return time.time() - self.start_time - self.pause_offset

    def _update_progress_bar(self, current_time: float) -> None:
        if self.duration > 0:
            width = self.progress_canvas.winfo_width()
            progress = current_time / self.duration
            fill_width = int(width * progress)
            self.progress_canvas.coords(self.progress_fill, 0, 0, fill_width, 8)

    def _update_time_display(self, current_time: float) -> None:
        self.current_time_label.configure(text=self._format_time(current_time))

    def _format_time(self, seconds: float) -> str:
        mins = int(seconds) // 60
        secs = int(seconds) % 60
        return f"{mins}:{secs:02d}"

    def _schedule_update(self) -> None:
        if self.is_playing:
            self._update_ui()
            self.root.after(self.update_interval, self._schedule_update)

    def _update_ui(self) -> None:
        current_time = self._get_current_time()

        self._update_progress_bar(current_time)
        self._update_time_display(current_time)

        idx = self._line_index_at_time(current_time)
        if idx != self.current_line_index:
            self.current_line_index = idx
            self._set_line_styles(idx)
            self._scroll_active_line_to_center(idx)

        if current_time >= self.duration:
            self._on_playback_finished()

    def _on_playback_finished(self) -> None:
        self.is_playing = False
        self.is_paused = False
        self.play_btn.configure(text="▶ Replay")
        self.status_label.configure(text="Finished")

    def _quit(self) -> None:
        try:
            pygame.mixer.music.stop()
            pygame.mixer.quit()
        except Exception:
            pass
        self.lyrics_canvas.unbind_all("<MouseWheel>")
        self.root.quit()
        self.root.destroy()

    def run(self) -> None:
        stage.info("Starting GUI karaoke player")
        self.root.mainloop()


def play_karaoke(
    audio_path: Path,
    transcript: Transcript,
    title: str = "Karaoke",
) -> None:
    """Open the GUI player with *audio_path* and timed *transcript*."""
    if not PYGAME_AVAILABLE:
        raise RuntimeError(
            "pygame is required for GUI playback.\n"
            "Install with: uv add pygame-ce"
        )

    player = KaraokeGUI(audio_path, transcript, title)
    player.run()
