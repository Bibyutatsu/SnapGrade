# macOS Standalone Desktop App — Compilation & Release Guide

SnapGrade can be packaged and run as a native standalone macOS desktop app bundle (`dist/SnapGrade.app`). It spawns the Python backend in a sidecar process and embeds the React UI in a Cocoa `WKWebView` window.

---

## Quick Install (Pre-built)

> **[⬇ Download SnapGrade-macOS.dmg (v0.2.0)](https://github.com/Bibyutatsu/SnapGrade/releases/download/v0.2.0/SnapGrade-macOS.dmg)**

No Python, `uv`, or Xcode required.

1. Open the `.dmg` and drag **SnapGrade** into your **Applications** folder.
2. Launch **SnapGrade** from Applications (right-click → Open on first run to bypass Gatekeeper).
3. To use the `snapgrade` CLI globally, open the app menu: **SnapGrade → Install Command Line Tool…**

> [!NOTE]
> CoreML models are downloaded to `~/.snapgrade/` on first use. The app bundles the full backend sidecar — no separate Python installation needed.

All releases and changelogs: [github.com/Bibyutatsu/SnapGrade/releases](https://github.com/Bibyutatsu/SnapGrade/releases)

---

## 1. Local Development & Compilation

To build and run the app locally on your Mac:

### Prerequisites
Make sure your python virtual environment is initialized and dependencies are synchronized:
```bash
uv sync --all-extras
uv pip install pyinstaller
```

### Step 1: Compile the Backend Sidecar
Compile the FastAPI backend using PyInstaller:
```bash
uv run python build_sidecar.py
```
This generates a directory of compiled binaries and modules under `dist/snapgrade_backend/` for instant startup. Heavy packages such as `torch` and `torchvision` are excluded to keep the bundle size small.

### Step 2: Compile the SwiftUI Wrapper & Assemble App
Compile the native Swift wrapper and assemble the `.app` bundle:
```bash
uv run python build_app.py
```
This script:
1. Compiles the Swift sources under `macapp/SnapGradeApp/` using the system Swift compiler (`swiftc`).
2. Structures the `dist/SnapGrade.app` bundle directory.
3. Embeds the sidecar python backend inside the bundle's `Resources` folder.
4. Loads `docs/images/logos/Dark_theme.svg`, scales it to maintain aspect ratio, draws it on a solid black background, and builds a macOS `AppIcon.icns`.
5. Registers the icon in the bundle `Info.plist`.
6. Performs local ad-hoc codesigning (required to run binaries on Apple Silicon macOS).

### Step 3: Run the App
Launch the compiled app from the terminal:
```bash
open dist/SnapGrade.app
```
Or double-click the `SnapGrade` application under `dist/` in Finder.

---

## 2. Packaging into a `.dmg` Installer (Optional)

To package the application into a user-friendly "drag-to-install" Disk Image (`.dmg`):

1. Install the packaging utility via Homebrew:
   ```bash
   brew install create-dmg
   ```
2. Build the installer:
   ```bash
   mkdir -p dist/dmg && cp -R dist/SnapGrade.app dist/dmg/
   create-dmg \
     --volname "SnapGrade" \
     --window-pos 200 120 \
     --window-size 600 400 \
     --icon-size 100 \
     --icon "SnapGrade.app" 175 120 \
     --app-drop-link 425 120 \
     "dist/SnapGrade-macOS.dmg" \
     "dist/dmg/"
   rm -rf dist/dmg
   ```
This outputs `dist/SnapGrade-macOS.dmg`.

---

## 3. CI/CD Release Automation & GitHub Releases

We have set up an automated release workflow in [.github/workflows/release.yml](file:///Users/oindrila/Projects/BlurDetector/.github/workflows/release.yml).

### Release Flow
When you push a version tag to GitHub:
```bash
git tag v0.2.0
git push origin v0.2.0
```
The workflow automatically:
1. Checks out the codebase.
2. Installs `uv` and PyInstaller.
3. Packages the Python sidecar backend and Swift app wrapper.
4. Generates the `.dmg` installer.
5. Code-signs and notarizes the `.dmg` if your Apple Developer credentials are set in GitHub secrets.
6. Uploads `SnapGrade-macOS.dmg` to a new draft Release on your repository.

### Configuring Apple Notarization Secrets
To prevent macOS Gatekeeper warnings ("Apple cannot check it for malicious software"), add the following secrets in your repository settings:
- `APPLE_CODESIGN_CERTIFICATE`: Base64 string of your Developer ID `.p12` certificate.
- `APPLE_CODESIGN_PASSWORD`: Password for the exported `.p12` certificate.
- `APPLE_ID`: Your Apple Developer email ID.
- `APPLE_ID_PASSWORD`: App-specific password generated via Apple ID portal.
- `APPLE_TEAM_ID`: Your 10-character Apple Team ID.

If these secrets are not configured, the workflow will fallback to ad-hoc codesigning and build an unsigned `.dmg` release.

---

## 4. UI Bundling & Development Design

> [!TIP]
> **No Frontend Build Steps Required**: The React UI in `ui/` runs via in-browser Babel compilation. When you update the React JSX/HTML files, they are automatically packaged directly by the `build_sidecar.py` script. You do not need to run any npm compiler commands before building or releasing the macOS app.
