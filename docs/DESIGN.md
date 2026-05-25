# SnapGrade Brand & UI Design System

This document outlines the visual identity and design system of SnapGrade. It serves as the specification for creating branded assets, logos, and UI components.

---

## 1. Typography & Hierarchy

SnapGrade uses a high-contrast typographic pairing that reflects its technical foundation (classical computer vision) and its artistic target (photography and triage).

### Branding & Headings
* **Font**: `Instrument Serif` (Fallback: `Georgia`, `serif`)
* **Styling**: Elegant, high-contrast, editorial serif.
* **Branding Convention**: `Snap` is styled in regular weight, while `Grade` is in italicized accent color (`Snap`*`Grade`*).

### UI Chrome & Data Panels
* **Font**: `JetBrains Mono` (Fallback: `monospace`) for the default `dark-film` theme; `DM Sans` (Fallback: `sans-serif`) for the `dark-modern` and `light-pro` themes.
* **Styling**: Tabular numerals, high legibility at small sizes, uppercase tracked caption headers.

---

## 2. Color Palettes

SnapGrade supports three calibrated themes matching different lighting conditions. 

### A. Dark Film (Default & Editing Suite)
Designed for low-light editing suites to reduce eye strain and preserve exposure judgment.
* **Background (`--c-bg`)**: `#0a0907` (Deep warm charcoal-black)
* **Panel Canvas (`--c-panel`)**: `#161310` (Warm near-black)
* **Accent Highlight (`--c-accent`)**: `#c1440e` (Burnt amber-orange)
* **Text (`--c-text`)**: `#ece5d3` (Soft cream)
* **Text Mute (`--c-mute`)**: `#6e6657` (Earthy mud-gray)
* **Status Amber (`--c-amber`)**: `#d4a017` (Warm gold)
* **Status Keeper (`--c-keeper`)**: `#8bbf4a` (Olive green)
* **Status Reject (`--c-danger`)**: `#e0492b` (Rust red)

### B. Dark Modern (Cool Slate)
* **Background (`--c-bg`)**: `#0f0f12` (Cool obsidian)
* **Panel Canvas (`--c-panel`)**: `#1a1a20` (Dark slate)
* **Accent Highlight (`--c-accent`)**: `#e05a35` (Bright coral)
* **Text (`--c-text`)**: `#f0ede8` (Cool white)

### C. Light Pro (Daylight/Color-Accurate)
* **Background (`--c-bg`)**: `#f0ede8` (Warm sand)
* **Panel Canvas (`--c-panel`)**: `#ffffff` (Pure white)
* **Accent Highlight (`--c-accent`)**: `#c1440e` (Burnt orange)
* **Text (`--c-text`)**: `#1a1714` (Deep charcoal)

---

## 3. Logo & Visual Elements Specifications

To align with the UI design system, all SnapGrade logos, banners, and icons must follow these rules:

1. **Colors**: Logo assets must strictly use the signature accent orange (`#c1440e` or `#e05a35`), paired with deep warm canvas tones (`#0a0907` / `#161310`) and warm cream (`#ece5d3`).
2. **Visual Motifs**:
   - **S + G Lettermark**: Incorporate the initials `S` (Snap) and `G` (Grade) integrated with camera lens/aperture shapes.
   - **Aperture / Iris**: 6-blade or 8-blade geometric lines representing camera shutters.
   - **Focal Target / Viewfinder**: Crosshair and target framing lines representing focus, sharpness detection, and triage.
3. **Geometry**: Use clean, mathematically closed shapes. Avoid open arcs unless balanced by crosshairs.
