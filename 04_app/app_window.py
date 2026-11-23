"""Tkinter interface for the Beam Designer."""

from __future__ import annotations

import csv
import json
import math
import textwrap
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, Rectangle

import beam_calculations as calc


BG = "#f3f6fa"
CARD = "#ffffff"
INK = "#182230"
MUTED = "#65758b"
ACCENT = "#2369c8"
GREEN = "#25855a"
AMBER = "#d48b16"
RED = "#c84646"
GRID = "#dce3ec"


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event: tk.Event | None = None) -> None:
        if self.window is not None:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.window = window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            window,
            text=self.text,
            justify="left",
            background="#172435",
            foreground="white",
            padx=9,
            pady=6,
            wraplength=330,
            font=("Segoe UI", 9),
        )
        label.pack()

    def hide(self, _event: tk.Event | None = None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class BeamDesigner:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Beam Designer")
        root.geometry("1440x920")
        root.minsize(1020, 700)
        root.configure(background=BG)
        self._configure_styles()

        self.refresh_after_id: str | None = None
        self.drag_point_index: int | None = None
        self.result: dict[str, Any] | None = None
        self.current_file: str | None = None
        self.point_rows: list[dict[str, Any]] = []
        self.uniform_rows: list[dict[str, Any]] = []
        self.point_counter = 0
        self.uniform_counter = 0

        self.support_var = tk.StringVar(value="Simply supported")
        self.span_var = tk.DoubleVar(value=20.0)
        self.material_var = tk.StringVar(value="Steel")
        self.section_var = tk.StringVar(value="W12x26")
        self.limit_var = tk.StringVar(value="L/360")
        self.status_var = tk.StringVar(value="Ready")
        self.reaction_var = tk.StringVar(value="")
        self.recommendation_var = tk.StringVar(value="")

        self._build_layout()
        self._bind_input_updates()
        self.add_uniform_load("1.0", "0.0", "20.0")
        self.refresh()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=INK, font=("Segoe UI", 10))
        style.configure("Card.TLabel", background=CARD, foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=INK, font=("Segoe UI", 19, "bold"))
        style.configure("Section.TLabel", background=BG, foreground=INK, font=("Segoe UI", 11, "bold"))
        style.configure("TButton", padding=(9, 5))
        style.configure("Accent.TButton", background=ACCENT, foreground="white", padding=(10, 6))
        style.map("Accent.TButton", background=[("active", "#1857a8")])
        style.configure("TLabelframe", background=BG)
        style.configure("TLabelframe.Label", background=BG, foreground=INK, font=("Segoe UI", 10, "bold"))

    def _build_layout(self) -> None:
        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Save", command=self.save_design)
        file_menu.add_command(label="Open", command=self.open_design)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.root.configure(menu=menu_bar)

        header = ttk.Frame(self.root, padding=(18, 13, 18, 8))
        header.pack(fill="x")
        ttk.Label(header, text="Beam Designer", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="Set up a beam, inspect its response, and compare sections",
            style="Muted.TLabel",
        ).pack(side="left", padx=(14, 0), pady=(7, 0))

        body = ttk.Frame(self.root, padding=(14, 0, 14, 14))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=0, minsize=350)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self.left_shell = ttk.Frame(body, width=350)
        self.left_shell.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.left_shell.grid_propagate(False)
        self.left_canvas = tk.Canvas(self.left_shell, background=BG, highlightthickness=0, width=350)
        left_scroll = ttk.Scrollbar(self.left_shell, orient="vertical", command=self.left_canvas.yview)
        self.left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side="right", fill="y")
        self.left_canvas.pack(side="left", fill="both", expand=True)
        self.left_panel = ttk.Frame(self.left_canvas, padding=(2, 2, 8, 12))
        self.left_window = self.left_canvas.create_window((0, 0), window=self.left_panel, anchor="nw")
        self.left_panel.bind("<Configure>", self._update_scroll_region)
        self.left_canvas.bind("<Configure>", self._resize_left_panel)
        self.left_canvas.bind_all("<MouseWheel>", self._mousewheel, add="+")

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        self._build_inputs()
        self._build_results(right)

    def _update_scroll_region(self, _event: tk.Event | None = None) -> None:
        self.left_canvas.configure(scrollregion=self.left_canvas.bbox("all"))

    def _resize_left_panel(self, event: tk.Event) -> None:
        self.left_canvas.itemconfigure(self.left_window, width=event.width)

    def _mousewheel(self, event: tk.Event) -> None:
        widget = self.root.winfo_containing(event.x_root, event.y_root)
        if widget is not None and str(widget).startswith(str(self.left_canvas)):
            self.left_canvas.yview_scroll(int(-event.delta / 120), "units")

    def _build_inputs(self) -> None:
        panel = self.left_panel
        ttk.Label(panel, text="Beam setup", style="Section.TLabel").pack(anchor="w", pady=(4, 8))
        setup = ttk.Frame(panel, padding=11, style="Card.TFrame")
        setup.pack(fill="x", pady=(0, 10))

        ttk.Label(setup, text="Support", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=3)
        self.support_combo = ttk.Combobox(
            setup, textvariable=self.support_var, values=("Simply supported", "Cantilever"),
            state="readonly", width=22,
        )
        self.support_combo.grid(row=0, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(setup, text="Span (ft)", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=3)
        span_line = ttk.Frame(setup, style="Card.TFrame")
        span_line.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=3)
        self.span_scale = tk.Scale(
            span_line, variable=self.span_var, from_=4, to=40, resolution=0.25,
            orient="horizontal", showvalue=False, length=135, background=CARD,
            highlightthickness=0, troughcolor="#dfe8f5", activebackground=ACCENT,
        )
        self.span_scale.pack(side="left", fill="x", expand=True)
        self.span_spin = ttk.Spinbox(
            span_line, textvariable=self.span_var, from_=4, to=40, increment=0.25, width=6,
        )
        self.span_spin.pack(side="left", padx=(6, 0))

        ttk.Label(setup, text="Material", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=3)
        self.material_combo = ttk.Combobox(
            setup, textvariable=self.material_var, values=calc.MATERIALS, state="readonly", width=22,
        )
        self.material_combo.grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(setup, text="Section", style="Card.TLabel").grid(row=3, column=0, sticky="w", pady=3)
        self.section_combo = ttk.Combobox(setup, textvariable=self.section_var, state="readonly", width=22)
        self.section_combo.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=3)
        ttk.Label(setup, text="Deflection limit", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=3)
        self.limit_combo = ttk.Combobox(
            setup, textvariable=self.limit_var, values=("L/240", "L/360"), state="readonly", width=22,
        )
        self.limit_combo.grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=3)
        setup.columnconfigure(1, weight=1)
        self.material_combo.bind("<<ComboboxSelected>>", self._material_changed)
        self._set_section_values()

        ttk.Label(panel, text="Loads", style="Section.TLabel").pack(anchor="w", pady=(3, 8))
        self.loads_frame = ttk.Frame(panel)
        self.loads_frame.pack(fill="x")
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x", pady=(8, 12))
        ttk.Button(buttons, text="+ Point load", command=self.add_point_load).pack(side="left", fill="x", expand=True)
        ttk.Button(buttons, text="+ Uniform load", command=self.add_uniform_load).pack(
            side="left", fill="x", expand=True, padx=(7, 0)
        )
        note = ttk.Label(
            panel,
            text="Downward loads are positive. Loads extending past the beam end are clipped.",
            style="Muted.TLabel",
            wraplength=315,
        )
        note.pack(anchor="w", pady=(0, 8))

    def _build_results(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, style="Card.TFrame", padding=(12, 9))
        top.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top.columnconfigure(0, weight=1)
        ttk.Label(top, textvariable=self.reaction_var, style="Card.TLabel", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(top, textvariable=self.status_var, style="CardMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(3, 0)
        )
        checks = ttk.Frame(top, style="Card.TFrame")
        checks.grid(row=0, column=1, rowspan=2, sticky="e", padx=(12, 0))
        self.bending_card = self._make_check_card(checks, "Bending", "fb = |Mmax| x 12 / Sx")
        self.bending_card.pack(side="left", padx=(0, 8))
        self.deflection_card = self._make_check_card(
            checks, "Deflection", "PASS when |ymax| <= L(in) / 240 or L(in) / 360."
        )
        self.deflection_card.pack(side="left")

        figure_frame = ttk.Frame(parent, style="Card.TFrame", padding=(7, 7, 7, 2))
        figure_frame.grid(row=1, column=0, sticky="nsew")
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        self.figure = Figure(figsize=(9.3, 7.1), dpi=100, facecolor=CARD)
        grid = self.figure.add_gridspec(4, 1, height_ratios=(1.05, 2.0, 2.0, 2.0), hspace=0.26)
        self.ax_beam = self.figure.add_subplot(grid[0, 0])
        self.ax_shear = self.figure.add_subplot(grid[1, 0], sharex=self.ax_beam)
        self.ax_moment = self.figure.add_subplot(grid[2, 0], sharex=self.ax_beam)
        self.ax_deflection = self.figure.add_subplot(grid[3, 0], sharex=self.ax_beam)
        self.figure.subplots_adjust(left=0.085, right=0.98, top=0.97, bottom=0.08)
        self.canvas = FigureCanvasTkAgg(self.figure, master=figure_frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("button_press_event", self._plot_press)
        self.canvas.mpl_connect("motion_notify_event", self._plot_motion)
        self.canvas.mpl_connect("button_release_event", self._plot_release)

        bottom = ttk.Frame(parent, style="Card.TFrame", padding=(12, 8))
        bottom.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.recommendation_var, style="Card.TLabel").grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 6)
        )
        self.export_button = ttk.Button(
            bottom, text="Export CSV", command=self.export_results, state="disabled"
        )
        self.export_button.grid(row=1, column=1, sticky="e", padx=(8, 0))
        self.calculation_sheet_button = ttk.Button(
            bottom, text="Calculation sheet PDF", command=self.export_calculation_sheet, state="disabled"
        )
        self.calculation_sheet_button.grid(row=1, column=2, sticky="e", padx=(8, 0))
        self.use_recommendation_button = ttk.Button(
            bottom, text="Use section", style="Accent.TButton", command=self._use_recommendation, state="disabled"
        )
        self.use_recommendation_button.grid(row=1, column=3, sticky="e", padx=(8, 0))

    def _make_check_card(self, parent: ttk.Frame, title: str, formula: str) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(10, 5), relief="solid")
        ttk.Label(card, text=title, style="Card.TLabel", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        actual = ttk.Label(card, text="--", style="CardMuted.TLabel")
        actual.pack(anchor="w")
        bar = tk.Canvas(card, width=190, height=10, background="#e8edf3", highlightthickness=0)
        bar.pack(fill="x", pady=(4, 3))
        status = ttk.Label(card, text="--", style="Card.TLabel", font=("Segoe UI", 9, "bold"))
        status.pack(anchor="w")
        card.actual_label = actual  # type: ignore[attr-defined]
        card.bar = bar  # type: ignore[attr-defined]
        card.status_label = status  # type: ignore[attr-defined]
        ToolTip(card, formula)
        ToolTip(actual, formula)
        return card

    def _bind_input_updates(self) -> None:
        self.span_var.trace_add("write", self._schedule_refresh)
        self.support_var.trace_add("write", self._schedule_refresh)
        self.section_var.trace_add("write", self._schedule_refresh)
        self.limit_var.trace_add("write", self._schedule_refresh)

    def _set_section_values(self) -> None:
        sections = calc.sections_for(self.material_var.get())
        self.section_combo.configure(values=tuple(sections.keys()))
        if self.section_var.get() not in sections:
            self.section_var.set(next(iter(sections)))

    def _material_changed(self, _event: tk.Event | None = None) -> None:
        self._set_section_values()
        self._schedule_refresh()

    def add_point_load(self, magnitude: str = "1.0", position: str | None = None) -> None:
        self.point_counter += 1
        if position is None:
            position = f"{self._default_point_position():.2f}"
        row: dict[str, Any] = {
            "id": self.point_counter,
            "magnitude": tk.StringVar(value=magnitude),
            "position": tk.StringVar(value=position),
        }
        self.point_rows.append(row)
        self._build_load_row(row, "point")
        self._schedule_refresh()

    def add_uniform_load(
        self, magnitude: str = "0.1", start: str = "0.0", end: str | None = None
    ) -> None:
        self.uniform_counter += 1
        if end is None:
            end = f"{self._span_value():.2f}"
        row: dict[str, Any] = {
            "id": self.uniform_counter,
            "magnitude": tk.StringVar(value=magnitude),
            "start": tk.StringVar(value=start),
            "end": tk.StringVar(value=end),
        }
        self.uniform_rows.append(row)
        self._build_load_row(row, "uniform")
        self._schedule_refresh()

    def _default_point_position(self) -> float:
        return self._span_value() if self.support_var.get() == "Cantilever" else self._span_value() / 2

    def _span_value(self) -> float:
        try:
            return float(self.span_var.get())
        except (tk.TclError, ValueError):
            return 20.0

    def _build_load_row(self, row: dict[str, Any], kind: str) -> None:
        frame = ttk.Frame(self.loads_frame, style="Card.TFrame", padding=(9, 7))
        frame.pack(fill="x", pady=(0, 7))
        row["frame"] = frame
        heading = "Point load" if kind == "point" else "Uniform load"
        ttk.Label(frame, text=heading, style="Card.TLabel", font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", columnspan=4
        )
        ttk.Button(
            frame, text="Remove", width=8, command=lambda r=row, k=kind: self._remove_load(r, k)
        ).grid(row=0, column=4, sticky="e")
        if kind == "point":
            labels = (("Magnitude (k)", "magnitude"), ("Position (ft)", "position"))
        else:
            labels = (("Magnitude (k/ft)", "magnitude"), ("Start (ft)", "start"), ("End (ft)", "end"))
        for col, (label, key) in enumerate(labels):
            ttk.Label(frame, text=label, style="CardMuted.TLabel").grid(
                row=1, column=col, sticky="w", padx=(0, 5), pady=(6, 1)
            )
            entry = ttk.Entry(frame, textvariable=row[key], width=10)
            entry.grid(row=2, column=col, sticky="ew", padx=(0, 5))
            row[key].trace_add("write", self._schedule_refresh)
            row.setdefault("entries", []).append(entry)
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        if kind == "uniform":
            frame.columnconfigure(2, weight=1)

    def _remove_load(self, row: dict[str, Any], kind: str) -> None:
        rows = self.point_rows if kind == "point" else self.uniform_rows
        if row in rows:
            rows.remove(row)
            row["frame"].destroy()
        self._schedule_refresh()

    def _schedule_refresh(self, *_args: Any) -> None:
        if self.refresh_after_id is not None:
            self.root.after_cancel(self.refresh_after_id)
        self.refresh_after_id = self.root.after(80, self.refresh)

    @staticmethod
    def _float_value(variable: tk.StringVar, label: str) -> float:
        value = float(variable.get())
        if not math.isfinite(value):
            raise ValueError(f"{label} must be a finite number.")
        return value

    def _read_inputs(self) -> dict[str, Any]:
        span = float(self.span_var.get())
        if not 4 <= span <= 40:
            raise ValueError("Span must be between 4 and 40 ft.")
        points = [
            {
                "magnitude": self._float_value(row["magnitude"], "Point load"),
                "position": self._float_value(row["position"], "Point-load position"),
            }
            for row in self.point_rows
        ]
        uniforms = [
            {
                "magnitude": self._float_value(row["magnitude"], "Uniform load"),
                "start": self._float_value(row["start"], "Uniform-load start"),
                "end": self._float_value(row["end"], "Uniform-load end"),
            }
            for row in self.uniform_rows
        ]
        return {
            "support": self.support_var.get(),
            "span_ft": span,
            "material": self.material_var.get(),
            "section_name": self.section_var.get(),
            "deflection_divisor": int(self.limit_var.get().split("/")[-1]),
            "point_loads": points,
            "uniform_loads": uniforms,
        }

    def save_design(self) -> None:
        try:
            inputs = self._read_inputs()
            calc.analyze_beam(**inputs)
        except (ValueError, tk.TclError, ZeroDivisionError) as exc:
            messagebox.showerror("Cannot save beam", str(exc), parent=self.root)
            return

        path = self.current_file
        if path is None:
            path = filedialog.asksaveasfilename(
                parent=self.root,
                title="Save beam",
                defaultextension=".json",
                filetypes=(("Beam Designer files", "*.json"), ("All files", "*.*")),
            )
            if not path:
                return

        document = {
            "format": "beam-designer",
            "version": 1,
            "support": inputs["support"],
            "span_ft": inputs["span_ft"],
            "material": inputs["material"],
            "section": inputs["section_name"],
            "deflection_limit": f"L/{inputs['deflection_divisor']}",
            "point_loads": inputs["point_loads"],
            "uniform_loads": inputs["uniform_loads"],
        }
        try:
            with open(path, "w", encoding="utf-8") as design_file:
                json.dump(document, design_file, indent=2)
                design_file.write("\n")
        except OSError as exc:
            messagebox.showerror("Cannot save beam", str(exc), parent=self.root)
            return

        self.current_file = path
        self._update_window_title()
        self.status_var.set(f"Saved {path}")

    def export_results(self) -> None:
        try:
            inputs = self._read_inputs()
            result = calc.analyze_beam(**inputs)
        except (ValueError, tk.TclError, ZeroDivisionError) as exc:
            self.export_button.configure(state="disabled")
            messagebox.showerror("Cannot export results", str(exc), parent=self.root)
            return

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export beam results",
            defaultextension=".csv",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(("x (ft)", "V (kips)", "M (kip-ft)", "Deflection (in)"))
                writer.writerows(
                    zip(
                        result["plot_x"],
                        result["plot_shear"],
                        result["plot_moment"],
                        result["plot_deflection"],
                    )
                )
        except (OSError, csv.Error) as exc:
            messagebox.showerror("Cannot export results", str(exc), parent=self.root)
            return
        self.status_var.set(f"Exported results to {path}")

    def export_calculation_sheet(self) -> None:
        try:
            inputs = self._read_inputs()
            result = calc.analyze_beam(**inputs)
        except (ValueError, tk.TclError, ZeroDivisionError) as exc:
            self.export_button.configure(state="disabled")
            self.calculation_sheet_button.configure(state="disabled")
            messagebox.showerror("Cannot create calculation sheet", str(exc), parent=self.root)
            return

        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save calculation sheet",
            defaultextension=".pdf",
            filetypes=(("PDF files", "*.pdf"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            self._write_calculation_sheet(path, result, inputs)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot create calculation sheet", str(exc), parent=self.root)
            return
        self.status_var.set(f"Saved calculation sheet to {path}")

    @staticmethod
    def _write_calculation_sheet(
        path: str, result: dict[str, Any], inputs: dict[str, Any]
    ) -> None:
        figure = Figure(figsize=(8.5, 11), dpi=150, facecolor="white")
        figure.text(
            0.075, 0.966, "Beam Design Calculation Sheet",
            fontsize=17, fontweight="bold", color=INK, va="top",
        )
        point_text = "; ".join(
            f"{load['magnitude']:g} k at {load['position']:g} ft"
            for load in inputs["point_loads"]
        ) or "None"
        uniform_text = "; ".join(
            f"{load['magnitude']:g} k/ft from {load['start']:g} to {load['end']:g} ft"
            for load in inputs["uniform_loads"]
        ) or "None"
        input_lines: list[str] = []
        for line in (
            f"Support: {inputs['support']}    Span: {inputs['span_ft']:g} ft",
            f"Material: {inputs['material']}    Section: {inputs['section_name']}    "
            f"Deflection limit: L/{inputs['deflection_divisor']}",
            f"Point loads: {point_text}",
            f"Uniform loads: {uniform_text}",
        ):
            input_lines.extend(textwrap.wrap(line, width=96, break_long_words=False) or [""])
        figure.text(
            0.075, 0.929, "BEAM INPUTS",
            fontsize=9.5, fontweight="bold", color=ACCENT, va="top",
        )
        input_top = 0.902
        figure.text(
            0.075, input_top, "\n".join(input_lines),
            fontsize=10, color=INK, va="top", linespacing=1.4,
        )
        input_bottom = input_top - len(input_lines) * 0.022
        checks_heading_y = input_bottom - 0.028
        figure.text(
            0.075, checks_heading_y, "DESIGN CHECKS",
            fontsize=9.5, fontweight="bold", color=ACCENT, va="top",
        )
        section = result["section"]
        bending_color = GREEN if result["bending_pass"] else RED
        deflection_color = GREEN if result["deflection_pass"] else RED
        bending_title_y = checks_heading_y - 0.027
        figure.text(
            0.075, bending_title_y, f"BENDING TEST: {'PASS' if result['bending_pass'] else 'FAIL'}",
            fontsize=10, fontweight="bold", color=bending_color, va="top",
        )
        bending_detail_y = bending_title_y - 0.023
        figure.text(
            0.075, bending_detail_y,
            f"Actual: {result['stress']:.2f} ksi    Allowable: {section['Fb']:.2f} ksi    "
            f"Ratio: {result['bending_ratio']:.0%}",
            fontsize=9.5, color=INK, va="top",
        )
        deflection_title_y = bending_detail_y - 0.033
        figure.text(
            0.075, deflection_title_y,
            f"DEFLECTION TEST: {'PASS' if result['deflection_pass'] else 'FAIL'}",
            fontsize=10, fontweight="bold", color=deflection_color, va="top",
        )
        deflection_detail_y = deflection_title_y - 0.023
        figure.text(
            0.075, deflection_detail_y,
            f"Actual: {result['max_deflection']:.3f} in    "
            f"Allowable: {result['deflection_limit']:.3f} in    "
            f"Ratio: {result['deflection_ratio']:.0%}",
            fontsize=9.5, color=INK, va="top",
        )
        chart_top = max(deflection_detail_y - 0.05, 0.34)
        grid = figure.add_gridspec(
            4, 1, left=0.135, right=0.965, bottom=0.07, top=chart_top,
            height_ratios=(0.8, 1, 1, 1), hspace=0.38,
        )
        ax_beam = figure.add_subplot(grid[0, 0])
        ax_shear = figure.add_subplot(grid[1, 0], sharex=ax_beam)
        ax_moment = figure.add_subplot(grid[2, 0], sharex=ax_beam)
        ax_deflection = figure.add_subplot(grid[3, 0], sharex=ax_beam)
        axes = (ax_beam, ax_shear, ax_moment, ax_deflection)
        for ax in axes:
            ax.set_facecolor("white")
            ax.tick_params(axis="both", labelsize=7, colors=MUTED)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color("#cbd5e1")
            ax.spines["bottom"].set_color("#cbd5e1")

        span = result["span_ft"]
        ax_beam.set_xlim(0, span)
        ax_beam.set_ylim(-0.65, 1.55)
        ax_beam.set_yticks([])
        ax_beam.set_title("Beam, supports, and loads", loc="left", fontsize=8, color=INK, pad=2)
        ax_beam.plot([0, span], [0, 0], color=INK, linewidth=3)
        if result["support"] == "Simply supported":
            ax_beam.add_patch(Polygon([[0, -0.06], [-0.23, -0.40], [0.23, -0.40]], color="#51677f"))
            ax_beam.add_patch(Polygon([[span, -0.06], [span - 0.23, -0.40], [span + 0.23, -0.40]], color="#51677f"))
        else:
            ax_beam.add_patch(Rectangle((-0.13, -0.42), 0.13, 0.84, color="#51677f"))
        for load in result["uniforms"]:
            a, b, magnitude = load["start"], load["end"], load["magnitude"]
            count = max(2, min(36, int((b - a) * 1.5) + 1))
            for xpos in np.linspace(a, b, count):
                ax_beam.annotate(
                    "", xy=(xpos, 0.08), xytext=(xpos, 0.84),
                    arrowprops={"arrowstyle": "-|>", "color": ACCENT, "lw": 0.8},
                )
            ax_beam.text(
                (a + b) / 2, 0.94, f"{magnitude:g} k/ft",
                ha="center", fontsize=7, color=ACCENT,
            )
        for load in result["points"]:
            xpos, magnitude = load["position"], load["magnitude"]
            ax_beam.annotate(
                "", xy=(xpos, 0.08), xytext=(xpos, 1.20),
                arrowprops={"arrowstyle": "-|>", "color": RED, "lw": 1.1},
            )
            ax_beam.text(xpos, 1.26, f"{magnitude:g} k", ha="center", fontsize=7, color=RED)
        reactions = result["reactions"]
        ax_beam.annotate(
            "", xy=(0, -0.02), xytext=(0, -0.52),
            arrowprops={"arrowstyle": "-|>", "color": GREEN, "lw": 1.0},
        )
        ax_beam.text(0.12, -0.28, f"{reactions['left']:.2f} k", fontsize=7, color=GREEN)
        if result["support"] == "Simply supported":
            ax_beam.annotate(
                "", xy=(span, -0.02), xytext=(span, -0.52),
                arrowprops={"arrowstyle": "-|>", "color": GREEN, "lw": 1.0},
            )
            ax_beam.text(
                span - 0.12, -0.28, f"{reactions['right']:.2f} k",
                fontsize=7, color=GREEN, ha="right",
            )
        ax_beam.grid(axis="x", color="#e2e8f0", linewidth=0.5)
        ax_beam.tick_params(axis="x", labelbottom=False, length=0)

        plot_x = result["plot_x"]
        charts = (
            (ax_shear, result["plot_shear"], "Shear V (kips)", "#dceafe", ACCENT),
            (ax_moment, result["plot_moment"], "Moment M (kip-ft)", "#e0f2e9", GREEN),
        )
        for ax, values, ylabel, fill, line_color in charts:
            ax.axhline(0, color="#64748b", linewidth=0.6)
            ax.fill_between(plot_x, values, 0, color=fill, alpha=0.95)
            ax.plot(plot_x, values, color=line_color, linewidth=1.0)
            ax.set_ylabel(ylabel, fontsize=7, color=INK)
            ax.grid(axis="x", color="#e2e8f0", linewidth=0.5)
            ax.grid(axis="y", color="#eef2f6", linewidth=0.4)
        max_shear_index = int(np.argmax(np.abs(result["shear"])))
        ax_shear.annotate(
            f"Max |V| = {result['max_shear']:.2f} k",
            xy=(result["max_shear_x"], result["shear"][max_shear_index]),
            xytext=(4, 4), textcoords="offset points", fontsize=6.5, color=ACCENT,
        )
        ax_moment.annotate(
            f"Max |M| = {result['max_moment']:.2f} kip-ft",
            xy=(result["max_moment_x"], result["max_moment_signed"]),
            xytext=(4, 4), textcoords="offset points", fontsize=6.5, color=GREEN,
        )
        y = result["deflection"]
        max_y = float(np.max(np.abs(y)))
        display_y = np.zeros_like(y) if max_y == 0 else -y * (0.48 / max_y)
        ax_deflection.axhline(0, color="#64748b", linewidth=0.6)
        ax_deflection.fill_between(result["x"], display_y, 0, color="#f7e7d5", alpha=0.95)
        ax_deflection.plot(result["x"], display_y, color="#c47a30", linewidth=1.1)
        ax_deflection.set_ylabel("Deflection y (in)", fontsize=7, color=INK)
        ax_deflection.set_xlabel("Position x (ft)", fontsize=7, color=INK)
        ax_deflection.grid(axis="x", color="#e2e8f0", linewidth=0.5)
        ax_deflection.grid(axis="y", color="#eef2f6", linewidth=0.4)
        max_y_index = int(np.argmax(np.abs(y)))
        ax_deflection.annotate(
            f"Max |y| = {result['max_deflection']:.3f} in",
            xy=(result["max_deflection_x"], display_y[max_y_index]),
            xytext=(4, 4), textcoords="offset points", fontsize=6.5, color="#9b5c20",
        )
        ax_deflection.set_xlim(0, span)
        ax_deflection.set_xticks(ax_beam.get_xticks())
        ax_shear.tick_params(axis="x", labelbottom=False)
        ax_moment.tick_params(axis="x", labelbottom=False)

        with PdfPages(path) as pdf:
            pdf.savefig(figure, facecolor="white")
        figure.clear()

    def open_design(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Open beam",
            filetypes=(("Beam Designer files", "*.json"), ("All files", "*.*")),
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as design_file:
                document = json.load(design_file)
            inputs = self._parse_design(document)
            # Run the standalone analyzer before changing the current design.
            calc.analyze_beam(**inputs)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError, OverflowError) as exc:
            messagebox.showerror("Cannot open beam", str(exc), parent=self.root)
            return

        self.support_var.set(inputs["support"])
        self.span_var.set(inputs["span_ft"])
        self.material_var.set(inputs["material"])
        self._set_section_values()
        self.section_var.set(inputs["section_name"])
        self.limit_var.set(f"L/{inputs['deflection_divisor']}")

        for row in self.point_rows + self.uniform_rows:
            row["frame"].destroy()
        self.point_rows.clear()
        self.uniform_rows.clear()
        for load in inputs["point_loads"]:
            self.add_point_load(repr(load["magnitude"]), repr(load["position"]))
        for load in inputs["uniform_loads"]:
            self.add_uniform_load(
                repr(load["magnitude"]), repr(load["start"]), repr(load["end"])
            )

        self.current_file = path
        self._update_window_title()
        if self.refresh_after_id is not None:
            self.root.after_cancel(self.refresh_after_id)
            self.refresh_after_id = None
        self.refresh()

    @staticmethod
    def _parse_design(document: Any) -> dict[str, Any]:
        if not isinstance(document, dict) or document.get("format") != "beam-designer":
            raise ValueError("This is not a Beam Designer file.")
        if document.get("version") != 1:
            raise ValueError("This Beam Designer file version is not supported.")

        support = document["support"]
        span_ft = float(document["span_ft"])
        material = document["material"]
        section_name = document["section"]
        limit_label = document["deflection_limit"]
        if support not in ("Simply supported", "Cantilever"):
            raise ValueError("The saved support type is not supported.")
        if not math.isfinite(span_ft) or not 4 <= span_ft <= 40:
            raise ValueError("The saved span must be between 4 and 40 ft.")
        if material not in calc.MATERIALS:
            raise ValueError("The saved material is not supported.")
        if section_name not in calc.sections_for(material):
            raise ValueError("The saved section does not belong to the selected material.")
        if limit_label not in ("L/240", "L/360"):
            raise ValueError("The saved deflection limit is not supported.")

        point_data = document["point_loads"]
        uniform_data = document["uniform_loads"]
        if not isinstance(point_data, list) or not isinstance(uniform_data, list):
            raise ValueError("Saved loads must be lists.")
        points = [
            {"magnitude": float(load["magnitude"]), "position": float(load["position"])}
            for load in point_data
            if isinstance(load, dict)
        ]
        uniforms = [
            {
                "magnitude": float(load["magnitude"]),
                "start": float(load["start"]),
                "end": float(load["end"]),
            }
            for load in uniform_data
            if isinstance(load, dict)
        ]
        if len(points) != len(point_data) or len(uniforms) != len(uniform_data):
            raise ValueError("Each saved load must be an object with its required values.")
        return {
            "support": support,
            "span_ft": span_ft,
            "material": material,
            "section_name": section_name,
            "deflection_divisor": int(limit_label.split("/")[-1]),
            "point_loads": points,
            "uniform_loads": uniforms,
        }

    def _update_window_title(self) -> None:
        if self.current_file:
            self.root.title(f"Beam Designer — {Path(self.current_file).name}")
        else:
            self.root.title("Beam Designer")

    def refresh(self) -> None:
        self.refresh_after_id = None
        try:
            inputs = self._read_inputs()
            result = calc.analyze_beam(**inputs)
        except (ValueError, tk.TclError, ZeroDivisionError) as exc:
            self.status_var.set(f"Input needs attention: {exc}")
            self.export_button.configure(state="disabled")
            self.calculation_sheet_button.configure(state="disabled")
            return
        self.result = result
        self.export_button.configure(state="normal")
        self.calculation_sheet_button.configure(state="normal")
        self.status_var.set("Results update as inputs change. Drag a point load to reposition it.")
        self._update_results(result)
        self._draw_beam_and_diagrams(result, inputs)

    def _update_results(self, result: dict[str, Any]) -> None:
        reactions = result["reactions"]
        if result["support"] == "Cantilever":
            reaction_text = (
                f"Reactions: {reactions['left']:.2f} k up    "
                f"Fixed-end moment: {reactions['fixed_moment']:.2f} kip-ft"
            )
        else:
            reaction_text = (
                f"Reactions: {reactions['left']:.2f} k left   "
                f"{reactions['right']:.2f} k right    "
                f"Max shear: {result['max_shear']:.2f} k"
            )
        self.reaction_var.set(reaction_text)

        section = result["section"]
        self._update_check_card(
            self.bending_card,
            f"{result['stress']:.2f} ksi / {section['Fb']:.2f} ksi  ({result['bending_ratio']:.0%})",
            result["bending_ratio"],
            result["bending_pass"],
        )
        self._update_check_card(
            self.deflection_card,
            f"{result['max_deflection']:.3f} in / {result['deflection_limit']:.3f} in  "
            f"({result['deflection_ratio']:.0%})",
            result["deflection_ratio"],
            result["deflection_pass"],
        )
        recommendation = result["recommendation"]
        if recommendation is None:
            self.recommendation_var.set("No section in this material passes both checks.")
            self.use_recommendation_button.configure(state="disabled")
        else:
            suffix = (
                f", {recommendation['properties']['weight']:.0f} lb/ft"
                if "weight" in recommendation["properties"] else ""
            )
            self.recommendation_var.set(
                f"Lightest passing section: {recommendation['name']}{suffix}"
            )
            self.use_recommendation_button.configure(state="normal")

    @staticmethod
    def _update_check_card(card: ttk.Frame, text: str, ratio: float, passes: bool) -> None:
        color = GREEN if ratio < 0.70 else AMBER if ratio <= 1.0 else RED
        card.actual_label.configure(text=text)  # type: ignore[attr-defined]
        bar = card.bar  # type: ignore[attr-defined]
        bar.delete("all")
        width = max(0.0, min(1.0, ratio)) * 190
        bar.create_rectangle(0, 0, width, 10, fill=color, outline="")
        card.status_label.configure(  # type: ignore[attr-defined]
            text="PASS" if passes else "FAIL",
            foreground=GREEN if passes else RED,
        )

    def _use_recommendation(self) -> None:
        if not self.result or not self.result["recommendation"]:
            return
        self.section_var.set(self.result["recommendation"]["name"])

    def _draw_beam_and_diagrams(self, result: dict[str, Any], inputs: dict[str, Any]) -> None:
        axes = (self.ax_beam, self.ax_shear, self.ax_moment, self.ax_deflection)
        for ax in axes:
            ax.clear()
            ax.set_facecolor(CARD)
            ax.tick_params(axis="both", labelsize=8, colors=MUTED)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.spines["left"].set_color(GRID)
            ax.spines["bottom"].set_color(GRID)
        span = result["span_ft"]
        self.ax_beam.set_xlim(0, span)
        self.ax_beam.set_ylim(-0.72, 1.85)
        self.ax_beam.set_yticks([])
        self.ax_beam.set_title("Beam and loads", loc="left", fontsize=9, color=INK, pad=3)
        self.ax_beam.plot([0, span], [0, 0], color=INK, linewidth=4, solid_capstyle="round")
        if result["support"] == "Simply supported":
            self.ax_beam.add_patch(Polygon([[0, -0.08], [-0.28, -0.50], [0.28, -0.50]], color="#51677f"))
            self.ax_beam.add_patch(Polygon([[span, -0.08], [span - 0.28, -0.50], [span + 0.28, -0.50]], color="#51677f"))
            self.ax_beam.plot([span - 0.38, span + 0.38], [-0.53, -0.53], color="#51677f", linewidth=1.3)
        else:
            self.ax_beam.add_patch(Rectangle((-0.17, -0.48), 0.17, 0.98, color="#51677f"))
            for y in np.linspace(-0.45, 0.45, 7):
                self.ax_beam.plot([-0.17, -0.34], [y, y - 0.17], color="#51677f", linewidth=0.8)

        for load in result["uniforms"]:
            a, b, w = load["start"], load["end"], load["magnitude"]
            count = max(2, min(48, int((b - a) * 2) + 1))
            for x in np.linspace(a, b, count):
                self.ax_beam.annotate(
                    "", xy=(x, 0.10), xytext=(x, 1.00),
                    arrowprops={"arrowstyle": "-|>", "color": ACCENT, "lw": 1.0},
                )
            self.ax_beam.plot([a, b], [1.02, 1.02], color=ACCENT, linewidth=1.0)
            self.ax_beam.text((a + b) / 2, 1.16, f"{w:g} k/ft", ha="center", color=ACCENT, fontsize=8)

        for load in result["points"]:
            x, magnitude = load["position"], load["magnitude"]
            self.ax_beam.annotate(
                "", xy=(x, 0.08), xytext=(x, 1.38),
                arrowprops={"arrowstyle": "-|>", "color": RED, "lw": 1.7},
            )
            self.ax_beam.text(x, 1.47, f"{magnitude:g} k", ha="center", color=RED, fontsize=8)

        reactions = result["reactions"]
        self.ax_beam.annotate(
            "", xy=(0, -0.02), xytext=(0, -0.60),
            arrowprops={"arrowstyle": "-|>", "color": GREEN, "lw": 1.4},
        )
        self.ax_beam.text(0.15, -0.34, f"{reactions['left']:.2f} k", color=GREEN, fontsize=8)
        if result["support"] == "Simply supported":
            self.ax_beam.annotate(
                "", xy=(span, -0.02), xytext=(span, -0.60),
                arrowprops={"arrowstyle": "-|>", "color": GREEN, "lw": 1.4},
            )
            self.ax_beam.text(span - 0.15, -0.34, f"{reactions['right']:.2f} k", color=GREEN, fontsize=8, ha="right")
        else:
            self.ax_beam.annotate(
                "", xy=(0.32, 0.70), xytext=(0.02, 0.70),
                arrowprops={
                    "arrowstyle": "-|>", "color": GREEN, "lw": 1.4,
                    "connectionstyle": "arc3,rad=0.9",
                },
            )
            self.ax_beam.text(
                0.42, 0.64, f"{reactions['fixed_moment']:.2f} kip-ft",
                color=GREEN, fontsize=8, va="center",
            )
        self.ax_beam.set_xticks(np.linspace(0, span, min(9, int(span / 4) + 1)))
        self.ax_beam.grid(axis="x", color=GRID, linewidth=0.6)
        self.ax_beam.tick_params(axis="x", labelbottom=False, length=0)

        x = result["plot_x"]
        panels = (
            (self.ax_shear, result["plot_shear"], "Shear V (kips)", "#dceafe", ACCENT),
            (self.ax_moment, result["plot_moment"], "Moment M (kip-ft)", "#e0f2e9", GREEN),
        )
        for ax, values, title, fill, line_color in panels:
            ax.axhline(0, color="#64748b", linewidth=0.8)
            ax.fill_between(x, values, 0, color=fill, alpha=0.95, step=None)
            ax.plot(x, values, color=line_color, linewidth=1.5)
            ax.set_ylabel(title, fontsize=8, color=INK)
            ax.grid(axis="x", color=GRID, linewidth=0.6)
            ax.grid(axis="y", color="#edf1f5", linewidth=0.5)

        i_m = int(np.argmax(np.abs(result["moment"])))
        self.ax_moment.annotate(
            f"{result['max_moment']:.2f} at {result['max_moment_x']:.2f} ft",
            xy=(result["max_moment_x"], result["moment"][i_m]),
            xytext=(5, 7), textcoords="offset points", fontsize=8, color=GREEN,
        )
        i_v = int(np.argmax(np.abs(result["shear"])))
        self.ax_shear.annotate(
            f"{result['max_shear']:.2f} at {result['max_shear_x']:.2f} ft",
            xy=(result["max_shear_x"], result["shear"][i_v]),
            xytext=(5, 7), textcoords="offset points", fontsize=8, color=ACCENT,
        )

        y = result["deflection"]
        display_scale = 0.0 if np.max(np.abs(y)) == 0 else 0.60 / np.max(np.abs(y))
        display_y = -y * display_scale
        self.ax_deflection.axhline(0, color="#64748b", linewidth=0.8)
        self.ax_deflection.fill_between(result["x"], display_y, 0, color="#f7e7d5", alpha=0.9)
        self.ax_deflection.plot(result["x"], display_y, color="#c47a30", linewidth=1.7)
        self.ax_deflection.set_ylabel("Deflection (in)", fontsize=8, color=INK)
        self.ax_deflection.set_xlabel("Position along beam (ft)", fontsize=8, color=INK)
        self.ax_deflection.grid(axis="x", color=GRID, linewidth=0.6)
        self.ax_deflection.grid(axis="y", color="#edf1f5", linewidth=0.5)
        self.ax_deflection.annotate(
            f"{result['max_deflection']:.3f} in at {result['max_deflection_x']:.2f} ft",
            xy=(result["max_deflection_x"], display_y[int(np.argmax(np.abs(y)))]),
            xytext=(5, 7), textcoords="offset points", fontsize=8, color="#9b5c20",
        )
        self.ax_deflection.set_xlim(0, span)
        self.ax_deflection.set_xticks(self.ax_beam.get_xticks())
        self.ax_shear.tick_params(axis="x", labelbottom=False)
        self.ax_moment.tick_params(axis="x", labelbottom=False)
        self.ax_beam.set_xlim(0, span)
        self._draw_hover_lines()
        self.canvas.draw_idle()

    def _draw_hover_lines(self) -> None:
        self.hover_lines = [
            self.ax_shear.axvline(0, color="#25364a", linestyle="--", linewidth=0.9, visible=False),
            self.ax_moment.axvline(0, color="#25364a", linestyle="--", linewidth=0.9, visible=False),
            self.ax_deflection.axvline(0, color="#25364a", linestyle="--", linewidth=0.9, visible=False),
        ]
        self.hover_text = self.ax_beam.text(
            0.99, 0.95, "", transform=self.ax_beam.transAxes, ha="right", va="top",
            fontsize=8, color=INK, bbox={"facecolor": CARD, "edgecolor": GRID, "alpha": 0.95},
        )

    def _plot_press(self, event: Any) -> None:
        if event.inaxes is not self.ax_beam or event.xdata is None or not self.result:
            return
        nearest: tuple[float, int] | None = None
        for i, load in enumerate(self.point_rows):
            try:
                px = float(load["position"].get())
            except ValueError:
                continue
            distance = abs(px - event.xdata)
            if nearest is None or distance < nearest[0]:
                nearest = (distance, i)
        if nearest is not None and nearest[0] <= self.result["span_ft"] * 0.025:
            self.drag_point_index = nearest[1]

    def _plot_motion(self, event: Any) -> None:
        if event.inaxes is self.ax_beam and self.drag_point_index is not None and event.xdata is not None:
            span = self._span_value()
            snapped = round(min(max(event.xdata, 0), span) * 4) / 4
            row = self.point_rows[self.drag_point_index]
            row["position"].set(f"{snapped:.2f}")
            return
        if event.inaxes not in (self.ax_shear, self.ax_moment, self.ax_deflection):
            return
        if event.xdata is None or not self.result:
            return
        x = min(max(float(event.xdata), 0.0), self.result["span_ft"])
        shear, moment, y = calc.sample_at(self.result, x)
        for line in self.hover_lines:
            line.set_xdata([x, x])
            line.set_visible(True)
        self.hover_text.set_text(f"x {x:.2f} ft   V {shear:.2f} k   M {moment:.2f} kip-ft   y {y:.3f} in")
        self.canvas.draw_idle()

    def _plot_release(self, _event: Any) -> None:
        self.drag_point_index = None


def run() -> None:
    root = tk.Tk()
    BeamDesigner(root)
    root.mainloop()

