import os
import shutil
import subprocess
import sys
from pathlib import Path

def build_mac_app():
    print("Building SnapGrade.app bundle...")
    workspace = Path(__file__).parent.resolve()
    
    # 1. Paths
    app_dir = workspace / "dist" / "SnapGrade.app"
    contents_dir = app_dir / "Contents"
    macos_dir = contents_dir / "MacOS"
    resources_dir = contents_dir / "Resources"
    
    # Clean previous build
    if app_dir.exists():
        shutil.rmtree(app_dir)
        
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. Compile Swift files
    print("Compiling Swift wrapper...")
    swift_files = list((workspace / "macapp" / "SnapGradeApp").glob("*.swift"))
    swift_files_str = [str(f) for f in swift_files]
    
    if not swift_files:
        print("Error: No Swift files found under macapp/SnapGradeApp/")
        sys.exit(1)
        
    sdk_path = subprocess.run(
        ["xcrun", "--show-sdk-path", "--sdk", "macosx"],
        capture_output=True, text=True, check=True
    ).stdout.strip()
    
    # We target macOS 14.0 as defined in Swift code/manifest
    target_arch = "arm64-apple-macosx14.0"
    
    swiftc_cmd = [
        "swiftc",
        "-O",
        "-sdk", sdk_path,
        "-target", target_arch,
        "-o", str(macos_dir / "SnapGrade"),
    ] + swift_files_str
    
    print(f"Running swiftc: {' '.join(swiftc_cmd)}")
    res = subprocess.run(swiftc_cmd)
    if res.returncode != 0:
        print("Error: Swift compilation failed.")
        sys.exit(res.returncode)
    print("Swift wrapper compiled successfully.")
    
    # 3. Copy Sidecar Backend
    sidecar_src = workspace / "dist" / "snapgrade_backend"
    if not sidecar_src.exists():
        print("Error: snapgrade_backend sidecar directory not found. Please build it first.")
        sys.exit(1)
        
    print("Copying sidecar backend into Resources...")
    shutil.copytree(sidecar_src, resources_dir / "snapgrade_backend")
    
    # 4. Create Info.plist
    info_plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>English</string>
    <key>CFBundleExecutable</key>
    <string>SnapGrade</string>
    <key>CFBundleIdentifier</key>
    <string>com.snapgrade.SnapGrade</string>
    <key>CFBundleInfoDictionaryVersion</key>
    <string>6.0</string>
    <key>CFBundleName</key>
    <string>SnapGrade</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1.1</string>
    <key>CFBundleSignature</key>
    <string>????</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
"""
    with (contents_dir / "Info.plist").open("w") as f:
        f.write(info_plist_content)
        
    # 5. Create PkgInfo
    with (contents_dir / "PkgInfo").open("w") as f:
        f.write("APPL????")
        
    # 6. Codesign the bundle (required for ARM64 macOS)
    print("Ad-hoc codesigning the app bundle...")
    codesign_cmd = [
        "codesign",
        "--force",
        "--deep",
        "--sign", "-",  # Ad-hoc signature
        str(app_dir)
    ]
    subprocess.run(codesign_cmd)
    
    print("SnapGrade.app built successfully at dist/SnapGrade.app!")

if __name__ == "__main__":
    build_mac_app()
