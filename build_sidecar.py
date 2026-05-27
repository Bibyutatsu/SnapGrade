import subprocess
import sys
from pathlib import Path

def build():
    print("Building SnapGrade sidecar backend...")
    
    # Define paths
    workspace = Path(__file__).parent.resolve()
    entrypoint = workspace / "snapgrade_entry.py"
    ui_dir = workspace / "ui"
    mp_site = workspace / ".venv/lib/python3.12/site-packages/mediapipe"
    mp_dylib = mp_site / "tasks/c/libmediapipe.dylib"
    
    # Build command
    cmd = [
        "pyinstaller",
        "--clean",
        "--name=snapgrade_backend",
        "--onedir",  # We want a directory of files for instant startup (no extraction overhead)
        "--noconfirm",
        f"--add-data={ui_dir}:ui",
        f"--add-data={workspace}/snapgrade/models_manifest.json:snapgrade",
        # Bundle libmediapipe.dylib so mediapipe.tasks.c can load it via importlib.resources.
        # --add-binary puts it on the dyld path; --add-data puts it where ctypes.CDLL loads it.
        f"--add-binary={mp_dylib}:mediapipe/tasks/c",
        f"--add-data={mp_dylib}:mediapipe/tasks/c",
        # Also bundle the pure-Python helpers that mediapipe_c_bindings imports
        f"--add-data={mp_site}/tasks/python/core/mediapipe_c_utils.py:mediapipe/tasks/python/core",
        f"--add-data={mp_site}/tasks/python/core/serial_dispatcher.py:mediapipe/tasks/python/core",
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
        "--hidden-import=mediapipe.tasks",
        "--hidden-import=mediapipe.tasks.c",
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

    # ── Post-build: fix mediapipe package namespace in _internal ──────────────
    # importlib.resources.files('mediapipe.tasks.c') requires __init__.py files
    # to exist in every package directory. PyInstaller copies the .dylib but not
    # the namespace markers, so we add them here.
    internal = workspace / "dist/snapgrade_backend/_internal"
    for pkg_dir in [
        internal / "mediapipe",
        internal / "mediapipe/tasks",
        internal / "mediapipe/tasks/c",
    ]:
        pkg_dir.mkdir(parents=True, exist_ok=True)
        init = pkg_dir / "__init__.py"
        if not init.exists():
            init.write_text("# namespace package marker added by build_sidecar.py\n")
            print(f"  created: {init.relative_to(workspace)}")
            
    print("SnapGrade sidecar backend built successfully in dist/snapgrade_backend/.")

if __name__ == "__main__":
    build()
