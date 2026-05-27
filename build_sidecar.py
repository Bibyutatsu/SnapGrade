import subprocess
import sys
from pathlib import Path

def build():
    print("Building SnapGrade sidecar backend...")
    
    # Define paths
    workspace = Path(__file__).parent.resolve()
    entrypoint = workspace / "snapgrade_entry.py"
    ui_dir = workspace / "ui"
    
    # Build command
    cmd = [
        "pyinstaller",
        "--clean",
        "--name=snapgrade_backend",
        "--onedir",  # We want a directory of files for instant startup (no extraction overhead)
        "--noconfirm",
        f"--add-data={ui_dir}:ui",
        f"--add-data={workspace}/snapgrade/models_manifest.json:snapgrade",
        # Excludes
        "--exclude-module=torch",
        "--exclude-module=torchvision",
        "--exclude-module=pytest",
        "--exclude-module=ruff",
        "--exclude-module=black",
        "--exclude-module=mypy",
        "--exclude-module=ipython",
        "--exclude-module=notebook",
        # Hidden imports
        "--hidden-import=uvicorn.protocols.http.h11_impl",
        "--hidden-import=uvicorn.protocols.http.httptools_impl",
        "--hidden-import=uvicorn.protocols.websockets.wsproto_impl",
        "--hidden-import=uvicorn.protocols.websockets.websockets_impl",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=uvicorn.loops.asyncio",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=uvicorn.lifespan.off",
        "--hidden-import=insightface.app",
        "--hidden-import=insightface.model_zoo",
        "--hidden-import=coremltools.models.model",
        "--hidden-import=onnxruntime",
        "--hidden-import=mediapipe",
        "--hidden-import=rawpy",
        "--hidden-import=imagehash",
        "--hidden-import=PIL.Image",
        "--hidden-import=h5py",
        str(entrypoint)
    ]
    
    print(f"Running command: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=workspace)
    if result.returncode != 0:
        print("Error: PyInstaller build failed.")
        sys.exit(result.returncode)
    print("SnapGrade sidecar backend built successfully in dist/snapgrade_backend/.")

if __name__ == "__main__":
    build()
