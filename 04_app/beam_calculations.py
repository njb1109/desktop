"""Beam statics, section data, and strength/deflection checks.

This module intentionally has no Tkinter or Matplotlib imports so the
engineering calculations can be reviewed independently of the interface.
All loads are downward-positive; x and span are in feet, moments in kip-ft,
and calculated deflections in inches.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np


STEEL_SECTIONS: dict[str, dict[str, float]] = {
    "W8x10": {"Ix": 30.8, "Sx": 7.81, "weight": 10.0, "E": 29000.0, "Fb": 30.0},
    "W10x12": {"Ix": 53.8, "Sx": 10.9, "weight": 12.0, "E": 29000.0, "Fb": 30.0},
    "W12x26": {"Ix": 204.0, "Sx": 33.4, "weight": 26.0, "E": 29000.0, "Fb": 30.0},
    "W14x22": {"Ix": 199.0, "Sx": 29.0, "weight": 22.0, "E": 29000.0, "Fb": 30.0},
    "W16x26": {"Ix": 301.0, "Sx": 38.4, "weight": 26.0, "E": 29000.0, "Fb": 30.0},
    "W18x35": {"Ix": 510.0, "Sx": 57.6, "weight": 35.0, "E": 29000.0, "Fb": 30.0},
    "W21x44": {"Ix": 843.0, "Sx": 81.6, "weight": 44.0, "E": 29000.0, "Fb": 30.0},
    "W24x55": {"Ix": 1350.0, "Sx": 114.0, "weight": 55.0, "E": 29000.0, "Fb": 30.0},
}

LUMBER_SECTIONS: dict[str, dict[str, float]] = {
    "2x8": {"Ix": 47.63, "Sx": 13.14, "E": 1600.0, "Fb": 0.900},
    "2x10": {"Ix": 98.93, "Sx": 21.39, "E": 1600.0, "Fb": 0.900},
    "2x12": {"Ix": 177.98, "Sx": 31.64, "E": 1600.0, "Fb": 0.900},
}

MATERIALS = ("Steel", "Douglas Fir-Larch No. 2")


def sections_for(material: str) -> dict[str, dict[str, float]]:
    if material == "Steel":
        return STEEL_SECTIONS
    if material == "Douglas Fir-Larch No. 2":
        return LUMBER_SECTIONS
    raise ValueError(f"Unknown material: {material}")


def _normalized_loads(
    span_ft: float,
    point_loads: list[dict[str, float]],
    uniform_loads: list[dict[str, float]],
) -> tuple[list[dict[str, float]], list[dict[str, float]]]:
    points: list[dict[str, float]] = []
    for load in point_loads:
        p = float(load["magnitude"])
        x = float(load["position"])
        if not (math.isfinite(p) and p >= 0):
            raise ValueError("Point load magnitudes must be finite and nonnegative.")
        if not (math.isfinite(x) and 0 <= x <= span_ft):
            raise ValueError("Point load positions must be within the beam span.")
        points.append({"magnitude": p, "position": x})

    uniforms: list[dict[str, float]] = []
    for load in uniform_loads:
        w = float(load["magnitude"])
        a = float(load["start"])
        b = float(load["end"])
        if not (math.isfinite(w) and w >= 0):
            raise ValueError("Uniform load magnitudes must be finite and nonnegative.")
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a < b):
            raise ValueError("Uniform load positions must satisfy 0 <= start < end.")
        # Loads beyond the right end are clipped; the original row remains in the UI.
        clipped_b = min(b, span_ft)
        if clipped_b > a:
            uniforms.append({"magnitude": w, "start": a, "end": clipped_b})
    return points, uniforms


def _trapz_cumulative(values: np.ndarray, x: np.ndarray) -> np.ndarray:
    out = np.zeros_like(x, dtype=float)
    if len(x) > 1:
        dx = np.diff(x)
        out[1:] = np.cumsum((values[:-1] + values[1:]) * 0.5 * dx)
    return out


def _deflection(
    x_ft: np.ndarray,
    moment_kip_ft: np.ndarray,
    span_ft: float,
    support: str,
    section: dict[str, float],
) -> np.ndarray:
    # Downward is positive. Convert M to kip-in and x to inches before EI integration.
    x_in = x_ft * 12.0
    curvature_per_in = -(moment_kip_ft * 12.0) / (section["E"] * section["Ix"])
    slope = _trapz_cumulative(curvature_per_in, x_in)
    y_raw = _trapz_cumulative(slope, x_in)
    if support == "Simply supported":
        slope_correction = -y_raw[-1] / (span_ft * 12.0)
        y_raw = y_raw + slope_correction * x_in
    # For a cantilever the integration already starts at y=0 and slope=0.
    return y_raw


def _make_grid(
    span_ft: float,
    points: list[dict[str, float]],
    uniforms: list[dict[str, float]],
) -> np.ndarray:
    # 0.01 ft spacing gives stable diagram extrema while staying inexpensive.
    regular = np.linspace(0.0, span_ft, int(math.ceil(span_ft * 100.0)) + 1)
    special = [p["position"] for p in points]
    for load in uniforms:
        special.extend((load["start"], load["end"]))
    return np.unique(np.concatenate((regular, np.asarray(special, dtype=float), [0.0, span_ft])))


def _actions_at(
    x_ft: np.ndarray,
    left_reaction: float,
    fixed_internal_moment: float,
    points: list[dict[str, float]],
    uniforms: list[dict[str, float]],
) -> tuple[np.ndarray, np.ndarray]:
    shear = np.full_like(x_ft, left_reaction, dtype=float)
    moment = fixed_internal_moment + left_reaction * x_ft
    for load in points:
        p = load["magnitude"]
        xp = load["position"]
        shear -= p * (x_ft >= xp)
        moment -= p * np.maximum(0.0, x_ft - xp)
    for load in uniforms:
        w, a, b = load["magnitude"], load["start"], load["end"]
        loaded_length = np.clip(x_ft - a, 0.0, b - a)
        shear -= w * loaded_length
        centroid = a + loaded_length * 0.5
        moment -= w * loaded_length * np.maximum(0.0, x_ft - centroid)
    return shear, moment


def _recommendation(
    material: str,
    span_ft: float,
    support: str,
    x_ft: np.ndarray,
    moment: np.ndarray,
    moment_max: float,
    deflection_limit_in: float,
) -> dict[str, Any] | None:
    sections = sections_for(material)
    passing: list[tuple[str, dict[str, float], float, float]] = []
    for name, props in sections.items():
        y = _deflection(x_ft, moment, span_ft, support, props)
        max_y = float(np.max(np.abs(y)))
        stress = moment_max * 12.0 / props["Sx"]
        if stress <= props["Fb"] and max_y <= deflection_limit_in:
            passing.append((name, props, stress, max_y))
    if not passing:
        return None
    if material == "Steel":
        passing.sort(key=lambda item: (item[1]["weight"], -item[1]["Ix"]))
    name, props, stress, max_y = passing[0]
    return {"name": name, "properties": dict(props), "stress": stress, "deflection": max_y}


def analyze_beam(
    *,
    support: str,
    span_ft: float,
    material: str,
    section_name: str,
    deflection_divisor: int,
    point_loads: list[dict[str, float]],
    uniform_loads: list[dict[str, float]],
) -> dict[str, Any]:
    """Analyze a simply supported beam or left-fixed cantilever."""
    span_ft = float(span_ft)
    if support not in ("Simply supported", "Cantilever"):
        raise ValueError("Choose Simply supported or Cantilever.")
    if not (math.isfinite(span_ft) and 0 < span_ft <= 40):
        raise ValueError("Span must be a finite positive value no greater than 40 ft.")
    if deflection_divisor not in (240, 360):
        raise ValueError("Deflection limit must be L/240 or L/360.")
    sections = sections_for(material)
    if section_name not in sections:
        raise ValueError(f"Unknown section for {material}: {section_name}")
    section = sections[section_name]
    points, uniforms = _normalized_loads(span_ft, point_loads, uniform_loads)

    total_load = sum(load["magnitude"] for load in points)
    total_moment_left = sum(load["magnitude"] * load["position"] for load in points)
    for load in uniforms:
        resultant = load["magnitude"] * (load["end"] - load["start"])
        centroid = (load["start"] + load["end"]) * 0.5
        total_load += resultant
        total_moment_left += resultant * centroid

    if support == "Simply supported":
        right_reaction = total_moment_left / span_ft
        left_reaction = total_load - right_reaction
        fixed_internal_moment = 0.0
        reactions = {"left": left_reaction, "right": right_reaction, "fixed_moment": None}
    else:
        left_reaction = total_load
        right_reaction = 0.0
        fixed_internal_moment = -total_moment_left
        reactions = {"left": left_reaction, "right": None, "fixed_moment": total_moment_left}

    x_ft = _make_grid(span_ft, points, uniforms)
    shear, moment = _actions_at(
        x_ft, left_reaction, fixed_internal_moment, points, uniforms
    )
    deflection = _deflection(x_ft, moment, span_ft, support, section)
    abs_moment = np.abs(moment)
    abs_shear = np.abs(shear)
    abs_deflection = np.abs(deflection)
    i_m = int(np.argmax(abs_moment))
    i_v = int(np.argmax(abs_shear))
    i_y = int(np.argmax(abs_deflection))
    max_moment = float(abs_moment[i_m])
    max_shear = float(abs_shear[i_v])
    max_deflection = float(abs_deflection[i_y])
    stress = max_moment * 12.0 / section["Sx"]
    deflection_limit_in = span_ft * 12.0 / deflection_divisor
    recommendation = _recommendation(
        material,
        span_ft,
        support,
        x_ft,
        moment,
        max_moment,
        deflection_limit_in,
    )

    # Duplicate point-load coordinates to draw shear jumps as vertical steps.
    plot_x: list[float] = []
    plot_shear: list[float] = []
    plot_moment: list[float] = []
    plot_deflection: list[float] = []
    event_positions = {load["position"] for load in points}
    for i, x in enumerate(x_ft):
        if x in event_positions:
            left_v = left_reaction
            for load in points:
                if load["position"] < x:
                    left_v -= load["magnitude"]
            for load in uniforms:
                left_v -= load["magnitude"] * np.clip(x - load["start"], 0.0, load["end"] - load["start"])
            plot_x.extend((float(x), float(x)))
            plot_shear.extend((float(left_v), float(shear[i])))
            plot_moment.extend((float(moment[i]), float(moment[i])))
            plot_deflection.extend((float(deflection[i]), float(deflection[i])))
        else:
            plot_x.append(float(x))
            plot_shear.append(float(shear[i]))
            plot_moment.append(float(moment[i]))
            plot_deflection.append(float(deflection[i]))

    return {
        "x": x_ft,
        "shear": shear,
        "moment": moment,
        "deflection": deflection,
        "plot_x": np.asarray(plot_x),
        "plot_shear": np.asarray(plot_shear),
        "plot_moment": np.asarray(plot_moment),
        "plot_deflection": np.asarray(plot_deflection),
        "points": points,
        "uniforms": uniforms,
        "reactions": reactions,
        "max_shear": max_shear,
        "max_shear_x": float(x_ft[i_v]),
        "max_moment": max_moment,
        "max_moment_x": float(x_ft[i_m]),
        "max_moment_signed": float(moment[i_m]),
        "max_deflection": max_deflection,
        "max_deflection_x": float(x_ft[i_y]),
        "stress": stress,
        "deflection_limit": deflection_limit_in,
        "bending_pass": stress <= section["Fb"],
        "deflection_pass": max_deflection <= deflection_limit_in,
        "bending_ratio": stress / section["Fb"] if section["Fb"] else math.inf,
        "deflection_ratio": max_deflection / deflection_limit_in if deflection_limit_in else math.inf,
        "section": dict(section),
        "recommendation": recommendation,
        "support": support,
        "span_ft": span_ft,
    }


def sample_at(result: dict[str, Any], x_ft: float) -> tuple[float, float, float]:
    """Return right-side shear and moment, plus interpolated deflection, at x."""
    x = min(max(float(x_ft), 0.0), result["span_ft"])
    reaction = result["reactions"]["left"]
    shear = float(reaction)
    moment = float(reaction * x)
    if result["support"] == "Cantilever":
        moment -= float(result["reactions"]["fixed_moment"])
    for load in result["points"]:
        p, xp = load["magnitude"], load["position"]
        if xp <= x:
            shear -= p
        moment -= p * max(0.0, x - xp)
    for load in result["uniforms"]:
        w, a, b = load["magnitude"], load["start"], load["end"]
        loaded_length = min(max(x - a, 0.0), b - a)
        shear -= w * loaded_length
        moment -= w * loaded_length * max(0.0, x - (a + loaded_length * 0.5))
    y = float(np.interp(x, result["x"], result["deflection"]))
    return shear, moment, y
