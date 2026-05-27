import os
import shutil
import subprocess
import sys
from pathlib import Path

def build_app_icon(svg_path: Path, icns_path: Path):
    print("Generating macOS app icon from SVG logo on black background...")
    try:
        from AppKit import NSImage, NSSize, NSBitmapImageRep, NSPNGFileType, NSGraphicsContext, NSColor, NSMakeRect, NSRectFill
        
        img = NSImage.alloc().initWithContentsOfFile_(str(svg_path))
        if img is None:
            print(f"Warning: Failed to load SVG file at {svg_path}")
            return False
            
        iconset_dir = svg_path.parent / "AppIcon.iconset"
        if iconset_dir.exists():
            shutil.rmtree(iconset_dir)
        iconset_dir.mkdir(exist_ok=True)
        
        # macOS standard sizes for iconsets
        sizes = [
            (16, "icon_16x16.png"),
            (32, "icon_16x16@2x.png"),
            (32, "icon_32x32.png"),
            (64, "icon_32x32@2x.png"),
            (128, "icon_128x128.png"),
            (256, "icon_128x128@2x.png"),
            (256, "icon_256x256.png"),
            (512, "icon_256x256@2x.png"),
            (512, "icon_512x512.png"),
            (1024, "icon_512x512@2x.png")
        ]
        
        for size_px, name in sizes:
            rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
                None, size_px, size_px, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
            )
            
            NSGraphicsContext.saveGraphicsState()
            NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
            
            # Fill with solid black background
            NSColor.blackColor().set()
            NSRectFill(NSMakeRect(0, 0, size_px, size_px))
            
            # Draw SVG image on top with a slight margin (10%) for native spacing
            margin = int(size_px * 0.1)
            inner_size = size_px - 2 * margin
            
            img.drawInRect_fromRect_operation_fraction_(
                NSMakeRect(margin, margin, inner_size, inner_size),
                NSMakeRect(0, 0, img.size().width, img.size().height),
                2, # NSCompositingOperationSourceOver
                1.0
            )
            
            NSGraphicsContext.restoreGraphicsState()
            
            png_data = rep.representationUsingType_properties_(NSPNGFileType, None)
            png_data.writeToFile_atomically_(str(iconset_dir / name), True)
            
        # Run iconutil to compile PNG set to .icns file
        subprocess.run(["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)], check=True)
        shutil.rmtree(iconset_dir)
        print(f"AppIcon.icns generated successfully at {icns_path}")
        return True
    except Exception as e:
        print(f"Warning: Failed to generate AppIcon.icns due to error: {e}")
        return False

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
    
    # 4. Generate AppIcon
    logo_svg = workspace / "docs" / "images" / "logos" / "Dark_theme.svg"
    if logo_svg.exists():
        build_app_icon(logo_svg, resources_dir / "AppIcon.icns")
    else:
        print(f"Warning: Logo SVG not found at {logo_svg}. Application icon will be skipped.")
    
    # 5. Create Info.plist
    info_plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>
    <string>English</string>
    <key>CFBundleExecutable</key>
    <string>SnapGrade</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
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
        
    # 6. Create PkgInfo
    with (contents_dir / "PkgInfo").open("w") as f:
        f.write("APPL????")
        
    # 7. Codesign the bundle (required for ARM64 macOS)
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
