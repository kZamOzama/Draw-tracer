import tkinter as tk
from tkinter import filedialog, ttk, messagebox
from PIL import Image, ImageTk
import ctypes
import os

# ─── Windows API Constants ───────────────────────────────────────────────────
GWL_EXSTYLE      = -20
WS_EX_LAYERED    = 0x80000
WS_EX_TRANSPARENT = 0x20


class FullscreenGhostTracer:
    """
    A ghost/tracing overlay tool.
    - Control Panel  : main Tk window with buttons, sliders, color palette.
    - Draw Zone      : borderless Toplevel that floats over other apps.
    """

    # ── Defaults ──────────────────────────────────────────────────────────────
    CONTROL_BG   = "#1a1a1a"
    HEADER_BG    = "#252525"
    ACCENT       = "#00ff88"
    LOCKED_COLOR = "#ff4444"
    BTN_CFG      = dict(
        bg="#2e2e2e", fg="white",
        activebackground="#00ff88", activeforeground="black",
        relief="flat", font=("Arial", 9, "bold"), pady=10,
        cursor="hand2"
    )

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Tracer Control Panel")
        self.root.geometry("340x580")
        self.root.configure(bg=self.CONTROL_BG)
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

        # State
        self.img_original: Image.Image | None = None
        self.tk_trace:     ImageTk.PhotoImage | None = None
        self.is_locked:    bool = False
        self.off_x:        int  = 0
        self.off_y:        int  = 0

        self._build_control_panel()
        self._build_draw_zone()

        # Keep canvas in sync whenever the draw window is resized
        self.draw_win.bind("<Configure>", lambda e: self._refresh_canvas_image())

    # ═════════════════════════════════════════════════════════════════════════
    # UI BUILDERS
    # ═════════════════════════════════════════════════════════════════════════

    def _build_control_panel(self):
        """
        Constructs every widget inside the control panel (main window).

        Layout
        ------
        • Header bar  – app title
        • Body frame  – all interactive controls
            ├─ Open Image button
            ├─ Lock / Unlock toggle button
            ├─ Opacity slider  (0.1 → 1.0)
            ├─ Zoom slider     (10 % → 300 %)
            ├─ Fit-to-Window button
            └─ Color palette strip  (populated after an image is loaded)
        """
        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=self.HEADER_BG, height=80)
        header.pack(fill="x")
        header.pack_propagate(False)

        # Animated gradient canvas for "kZam" branding
        self._name_canvas = tk.Canvas(
            header, bg=self.HEADER_BG, highlightthickness=0,
            width=340, height=80
        )
        self._name_canvas.pack(fill="both", expand=True)

        # Ghost emoji (static, left side)
        self._name_canvas.create_text(
            24, 40, text="👻", font=("Segoe UI Emoji", 18), anchor="center"
        )

        # Sub-label "TRACER HUB" (static, small, below name)
        self._name_canvas.create_text(
            190, 62, text="TRACER HUB",
            fill="#444", font=("Courier", 15, "bold"), anchor="center"
        )

        # The animated "kZam" text — drawn with per-frame color cycling
        self._name_text_id = self._name_canvas.create_text(
            190, 34, text="kZam",
            font=("Courier", 26, "bold"), anchor="center",
            fill=self.ACCENT
        )

        # Gradient stop colours (RGB tuples) to cycle through
        self._grad_stops = [
            (0, 255, 136),   # #00ff88  mint
            (0, 200, 255),   # #00c8ff  cyan
            (130, 80, 255),  # #8250ff  violet
            (255, 60, 180),  # #ff3cb4  pink
            (255, 180, 0),   # #ffb400  amber
            (0, 255, 136),   # back to mint (loop)
        ]
        self._grad_t   = 0.0   # 0.0 → 1.0 through each segment
        self._grad_seg = 0     # current segment index
        self._animate_name()

        # ── Body ──────────────────────────────────────────────────────────────
        body = tk.Frame(self.root, bg=self.CONTROL_BG, padx=20, pady=15)
        body.pack(fill="both", expand=True)

        # Open image
        tk.Button(
            body, text="📂  OPEN IMAGE",
            command=self.load_image, **self.BTN_CFG
        ).pack(fill="x", pady=4)

        # Lock toggle
        self.lock_btn = tk.Button(
            body, text="🔓  UNLOCKED  (Move / Resize)",
            command=self.toggle_lock, **self.BTN_CFG
        )
        self.lock_btn.pack(fill="x", pady=4)

        self._separator(body)

        # Opacity
        tk.Label(
            body, text="OPACITY", fg="#888",
            bg=self.CONTROL_BG, font=("Arial", 8, "bold")
        ).pack(anchor="w")
        self.opacity_var = tk.DoubleVar(value=0.5)
        self.opacity_scale = ttk.Scale(
            body, from_=0.1, to=1.0, orient="horizontal",
            variable=self.opacity_var,
            command=lambda v: self._apply_opacity(float(v))
        )
        self.opacity_scale.pack(fill="x", pady=(2, 10))

        # Zoom
        tk.Label(
            body, text="ZOOM  (%)", fg="#888",
            bg=self.CONTROL_BG, font=("Arial", 8, "bold")
        ).pack(anchor="w")
        self.zoom_var = tk.IntVar(value=100)
        zoom_row = tk.Frame(body, bg=self.CONTROL_BG)
        zoom_row.pack(fill="x", pady=(2, 4))
        self.zoom_scale = ttk.Scale(
            zoom_row, from_=10, to=300, orient="horizontal",
            variable=self.zoom_var,
            command=lambda v: self._on_zoom_change(int(float(v)))
        )
        self.zoom_scale.pack(side="left", fill="x", expand=True)
        self.zoom_label = tk.Label(
            zoom_row, textvariable=self.zoom_var,
            fg=self.ACCENT, bg=self.CONTROL_BG,
            font=("Arial", 8, "bold"), width=4
        )
        self.zoom_label.pack(side="left", padx=(6, 0))

        # Fit-to-window shortcut
        tk.Button(
            body, text="⛶  FIT TO WINDOW",
            command=self._fit_to_window, **self.BTN_CFG
        ).pack(fill="x", pady=4)

        self._separator(body)

        # Color palette
        tk.Label(
            body, text="COLOR PALETTE  (sampled from image)",
            fg="#888", bg=self.CONTROL_BG, font=("Arial", 8, "bold")
        ).pack(anchor="w", pady=(0, 4))
        self.palette_frame = tk.Frame(body, bg=self.CONTROL_BG)
        self.palette_frame.pack(fill="x")

        # Status bar at the bottom of the control panel
        self.status_var = tk.StringVar(value="No image loaded.")
        tk.Label(
            self.root, textvariable=self.status_var,
            fg="#555", bg=self.CONTROL_BG,
            font=("Arial", 8), anchor="w", padx=20
        ).pack(fill="x", side="bottom", pady=(0, 6))

    def _build_draw_zone(self):
        """
        Creates the floating, borderless draw/overlay window (Toplevel).

        Key properties
        --------------
        • overrideredirect(True)  – removes the OS title-bar and borders.
        • -alpha                  – makes the whole window semi-transparent.
        • The canvas sits inside and holds the reference image.
        • A small green resize handle is placed at the bottom-right corner.
        • Drag and resize bindings are wired to the canvas (active only
          when NOT locked).
        """
        self.draw_win = tk.Toplevel(self.root)
        self.draw_win.geometry("600x600+420+80")
        self.draw_win.overrideredirect(True)   # no title bar
        self.draw_win.attributes("-topmost", True)
        self.draw_win.attributes("-alpha", self.opacity_var.get())
        self.draw_win.configure(bg="black")

        # Canvas
        self.canvas = tk.Canvas(
            self.draw_win, bg="black",
            highlightthickness=2,
            highlightbackground=self.ACCENT
        )
        self.canvas.pack(fill="both", expand=True)

        # Drag bindings
        self.canvas.bind("<ButtonPress-1>",  self._drag_start)
        self.canvas.bind("<B1-Motion>",      self._drag_move)

        # Resize handle (15×15 square, bottom-right)
        self.resizer = tk.Frame(self.draw_win, bg=self.ACCENT, cursor="sizing")
        self.resizer.place(relx=1.0, rely=1.0, anchor="se", width=15, height=15)
        self.resizer.bind("<ButtonPress-1>", self._resize_start)
        self.resizer.bind("<B1-Motion>",     self._resize_move)

    # ═════════════════════════════════════════════════════════════════════════
    # IMAGE LOADING & RENDERING
    # ═════════════════════════════════════════════════════════════════════════

    def load_image(self):
        """
        Opens a file-picker dialog, loads the chosen image into memory,
        renders it on the canvas, and refreshes the color palette.

        Supports any format PIL recognises (PNG, JPEG, BMP, WEBP, etc.).
        The image is stored as self.img_original so it can be re-scaled
        losslessly whenever the window is resized.
        """
        path = filedialog.askopenfilename(
            title="Select reference image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tiff"),
                ("All files",   "*.*"),
            ]
        )
        if not path:
            return  # user cancelled

        try:
            self.img_original = Image.open(path).convert("RGBA")
        except Exception as exc:
            messagebox.showerror("Load error", f"Could not open image:\n{exc}")
            return

        filename = os.path.basename(path)
        w, h = self.img_original.size
        self.status_var.set(f"{filename}  ({w} × {h} px)")

        self._refresh_canvas_image()
        self._extract_palette()

    def _refresh_canvas_image(self):
        """
        Re-renders self.img_original onto the canvas at the current zoom level.

        Called automatically on:
        • initial image load
        • window resize  (<Configure> event)
        • zoom slider change

        The zoom value is a percentage of the *canvas* size, so 100 % means
        the image fills the canvas exactly.  Values < 100 leave black borders;
        values > 100 let the image extend beyond the visible area (useful for
        inspecting detail while tracing).
        """
        if self.img_original is None:
            return

        cw = max(self.draw_win.winfo_width(),  1)
        ch = max(self.draw_win.winfo_height(), 1)

        zoom  = self.zoom_var.get() / 100.0
        new_w = max(1, int(cw * zoom))
        new_h = max(1, int(ch * zoom))

        img_resized   = self.img_original.resize((new_w, new_h), Image.Resampling.LANCZOS)
        self.tk_trace = ImageTk.PhotoImage(img_resized)

        self.canvas.delete("img")
        # Centre the image inside the canvas
        self.canvas.create_image(cw // 2, ch // 2, image=self.tk_trace,
                                 tags="img", anchor="center")

    def _fit_to_window(self):
        """
        Resets the zoom slider to 100 % so the image fills the draw window
        exactly.  Handy after manual zooming.
        """
        self.zoom_var.set(100)
        self._refresh_canvas_image()

    def _extract_palette(self):
        """
        Samples 12 evenly-spaced pixel columns from the image (after
        squashing it to a 12×1 strip) and displays the resulting colours
        as small swatches in the control panel.

        Clicking a swatch copies its hex code to the clipboard.
        """
        for w in self.palette_frame.winfo_children():
            w.destroy()

        strip = self.img_original.convert("RGB").resize((12, 1), Image.Resampling.LANCZOS)
        for i in range(12):
            r, g, b = strip.getpixel((i, 0))
            hex_color = f"#{r:02x}{g:02x}{b:02x}"

            swatch = tk.Frame(
                self.palette_frame,
                bg=hex_color, width=22, height=22,
                cursor="hand2"
            )
            swatch.pack(side="left", padx=1)
            swatch.bind("<Button-1>", lambda e, c=hex_color: self._copy_color(c))

            # Tooltip-style label on hover
            tip = tk.Label(
                self.root, text=hex_color,
                fg="white", bg="#333",
                font=("Arial", 7), padx=4
            )
            swatch.bind("<Enter>", lambda e, t=tip, s=swatch: t.place(
                x=s.winfo_x() + 20, y=s.winfo_y() - 5,
                in_=self.palette_frame
            ))
            swatch.bind("<Leave>", lambda e, t=tip: t.place_forget())

    def _copy_color(self, hex_color: str):
        """
        Copies hex_color (e.g. '#1a2b3c') to the system clipboard and
        briefly flashes the status bar to confirm.
        """
        self.root.clipboard_clear()
        self.root.clipboard_append(hex_color)
        self.status_var.set(f"Copied {hex_color} to clipboard ✓")
        self.root.after(2000, lambda: self.status_var.set(
            "" if self.img_original is None else self.status_var.get()
        ))

    # ═════════════════════════════════════════════════════════════════════════
    # OPACITY & ZOOM
    # ═════════════════════════════════════════════════════════════════════════

    def _apply_opacity(self, value: float):
        """
        Sets the transparency of the entire draw window.

        Parameters
        ----------
        value : float
            A number between 0.1 (nearly invisible) and 1.0 (fully opaque).
            Passed directly from the opacity slider's -command callback.
        """
        self.draw_win.attributes("-alpha", value)

    def _on_zoom_change(self, value: int):
        """
        Triggered by the zoom slider.  Updates the label and re-renders
        the image on the canvas.

        Parameters
        ----------
        value : int
            Zoom level in percent (10–300).
        """
        self.zoom_var.set(value)
        self._refresh_canvas_image()

    # ═════════════════════════════════════════════════════════════════════════
    # LOCK / CLICK-THROUGH
    # ═════════════════════════════════════════════════════════════════════════

    def toggle_lock(self):
        """
        Switches between two modes:

        UNLOCKED  – the draw window can be dragged and resized; mouse events
                    are consumed by the overlay (you interact with the overlay).

        LOCKED    – the draw window becomes click-through using the Windows
                    WS_EX_TRANSPARENT extended style, so all mouse events fall
                    through to whatever application is beneath it.  This lets
                    you draw on a canvas app (Photoshop, Krita, etc.) while
                    the ghost image stays visible on top.
        """
        self.is_locked = not self.is_locked

        if self.is_locked:
            self.lock_btn.config(
                text="🔒  LOCKED  (Drawing Mode)",
                bg=self.LOCKED_COLOR
            )
            self.canvas.config(highlightbackground=self.LOCKED_COLOR)
            self.resizer.place_forget()
            self._set_click_through(True)
        else:
            self.lock_btn.config(
                text="🔓  UNLOCKED  (Move / Resize)",
                bg="#2e2e2e"
            )
            self.canvas.config(highlightbackground=self.ACCENT)
            self.resizer.place(relx=1.0, rely=1.0, anchor="se",
                               width=15, height=15)
            self._set_click_through(False)

    def _set_click_through(self, enabled: bool):
        """
        Adds or removes the WS_EX_TRANSPARENT Windows extended style on
        the draw window so that mouse clicks either pass through it or are
        captured by it.

        Parameters
        ----------
        enabled : bool
            True  → make the window click-through (locked/drawing mode).
            False → restore normal mouse capture (move/resize mode).

        Notes
        -----
        This uses ctypes to call the Win32 API directly.
        WS_EX_LAYERED must already be set (Tkinter sets it via -alpha) for
        WS_EX_TRANSPARENT to work correctly.
        """
        try:
            hwnd   = ctypes.windll.user32.GetParent(self.draw_win.winfo_id())
            styles = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if enabled:
                styles |= WS_EX_TRANSPARENT | WS_EX_LAYERED
            else:
                styles &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, styles)
        except Exception as exc:
            # Non-Windows platforms will raise AttributeError; handle gracefully
            messagebox.showwarning(
                "Platform warning",
                f"Click-through is only supported on Windows.\n({exc})"
            )

    # ═════════════════════════════════════════════════════════════════════════
    # DRAG (move the draw window)
    # ═════════════════════════════════════════════════════════════════════════

    def _drag_start(self, event: tk.Event):
        """
        Records the cursor's offset from the draw-window's top-left corner
        at the moment the user presses the mouse button.

        This offset is used in _drag_move to keep the window under the
        cursor as it is dragged around the screen.

        Only active when NOT locked.
        """
        if self.is_locked:
            return
        self.off_x = event.x_root - self.draw_win.winfo_x()
        self.off_y = event.y_root - self.draw_win.winfo_y()

    def _drag_move(self, event: tk.Event):
        """
        Repositions the draw window so it follows the cursor.

        Called continuously while the left mouse button is held and the
        mouse moves (B1-Motion).  Only active when NOT locked.
        """
        if self.is_locked:
            return
        new_x = event.x_root - self.off_x
        new_y = event.y_root - self.off_y
        self.draw_win.geometry(f"+{new_x}+{new_y}")

    # ═════════════════════════════════════════════════════════════════════════
    # RESIZE (drag the bottom-right handle)
    # ═════════════════════════════════════════════════════════════════════════

    def _resize_start(self, event: tk.Event):
        """
        Stores the initial geometry when the resize handle is first pressed.
        Not strictly necessary here because _resize_move computes the new
        size from absolute screen coordinates, but kept for potential
        future use (e.g. aspect-ratio locking).
        """
        self._resize_origin_w = self.draw_win.winfo_width()
        self._resize_origin_h = self.draw_win.winfo_height()

    def _resize_move(self, event: tk.Event):
        """
        Resizes the draw window by computing the distance from the window's
        top-left corner to the current cursor position.

        A minimum of 80×80 px is enforced to prevent the window from
        becoming too small to interact with.

        After resizing, _refresh_canvas_image() is called so the image
        re-scales to fill the new dimensions without looking blurry.
        """
        if self.is_locked:
            return
        new_w = max(80, event.x_root - self.draw_win.winfo_x())
        new_h = max(80, event.y_root - self.draw_win.winfo_y())
        self.draw_win.geometry(f"{new_w}x{new_h}")
        self._refresh_canvas_image()

    # ═════════════════════════════════════════════════════════════════════════
    # HELPERS
    # ═════════════════════════════════════════════════════════════════════════

    def _animate_name(self):
        """
        Cycles the "kZam" text through a smooth multi-stop colour gradient
        using linear interpolation between RGB stop pairs.

        Each frame advances self._grad_t by a small step inside the current
        segment.  When t reaches 1.0 the next segment begins, creating a
        seamless infinite loop:

            mint → cyan → violet → pink → amber → mint → …

        The interpolated colour is also used to repaint a soft glow shadow
        (offset by 2 px) so the text appears to pulse with light.
        """
        stops = self._grad_stops
        seg   = self._grad_seg
        t     = self._grad_t

        r1, g1, b1 = stops[seg]
        r2, g2, b2 = stops[(seg + 1) % len(stops)]

        # Linear interpolation
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        color = f"#{r:02x}{g:02x}{b:02x}"

        # Dimmer glow colour (40 % brightness of main colour)
        gr = int(r * 0.35)
        gg = int(g * 0.35)
        gb = int(b * 0.35)
        glow_color = f"#{gr:02x}{gg:02x}{gb:02x}"

        # Update or recreate glow shadow behind main text
        self._name_canvas.delete("glow")
        for offset in ((3, 3), (-3, -3), (3, -3), (-3, 3)):
            self._name_canvas.create_text(
                190 + offset[0], 34 + offset[1],
                text="kZam", font=("Courier", 26, "bold"),
                fill=glow_color, anchor="center", tags="glow"
            )

        # Repaint the main text on top
        self._name_canvas.itemconfig(self._name_text_id, fill=color)
        self._name_canvas.tag_raise(self._name_text_id)

        # Advance t; move to next segment when t wraps past 1.0
        self._grad_t += 0.018
        if self._grad_t >= 1.0:
            self._grad_t   = 0.0
            self._grad_seg = (self._grad_seg + 1) % (len(stops) - 1)

        # Schedule next frame (~60 fps)
        self.root.after(16, self._animate_name)

    @staticmethod
    def _separator(parent: tk.Frame):
        """
        Draws a thin horizontal rule inside parent to visually group
        related controls in the panel.
        """
        tk.Frame(parent, bg="#333", height=1).pack(fill="x", pady=8)


# ─── Entry point ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app = FullscreenGhostTracer(root)
    root.mainloop()