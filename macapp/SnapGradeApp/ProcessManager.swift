import Foundation
import Combine

class ProcessManager: ObservableObject {
    @Published var isBackendReady = false
    @Published var errorMessage: String? = nil
    
    private var process: Process?
    private var port: Int = 8765
    private var pingTimer: Timer?
    
    private func getBackendPath() -> String? {
        if let path = Bundle.main.path(forResource: "snapgrade_backend/snapgrade_backend", ofType: nil) {
            return path
        }
        let devPath = Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent("snapgrade_backend/snapgrade_backend").path
        if FileManager.default.fileExists(atPath: devPath) {
            return devPath
        }
        return nil
    }
    
    func startBackend() {
        guard let backendPath = getBackendPath() else {
            self.errorMessage = "Failed to locate snapgrade_backend in App Bundle Resources."
            return
        }
        launchBinary(at: backendPath)
    }
    
    func runSetup(onProgress: @escaping (String) -> Void, onCompletion: @escaping (Bool, String?) -> Void) {
        guard let backendPath = getBackendPath() else {
            onCompletion(false, "Failed to locate snapgrade_backend binary.")
            return
        }
        
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: backendPath)
        proc.arguments = ["setup"]
        proc.environment = ProcessInfo.processInfo.environment
        
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = pipe
        
        let fileHandle = pipe.fileHandleForReading
        fileHandle.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty, let str = String(data: data, encoding: .utf8) {
                DispatchQueue.main.async {
                    onProgress(str)
                }
            }
        }
        
        proc.terminationHandler = { process in
            fileHandle.readabilityHandler = nil
            DispatchQueue.main.async {
                if process.terminationStatus == 0 {
                    onCompletion(true, nil)
                } else {
                    onCompletion(false, "Setup exited with error code \(process.terminationStatus)")
                }
            }
        }
        
        do {
            try proc.run()
        } catch {
            fileHandle.readabilityHandler = nil
            onCompletion(false, error.localizedDescription)
        }
    }
    
    private func launchBinary(at path: String) {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: path)
        proc.arguments = ["serve", "--port", String(port)]
        
        // Inherit user environment variables (important for Path, dynamic links, etc.)
        proc.environment = ProcessInfo.processInfo.environment
        
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        proc.standardOutput = stdoutPipe
        proc.standardError = stderrPipe
        
        // Log backend output to system console
        stdoutPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty, let str = String(data: data, encoding: .utf8) {
                print("[Backend STDOUT] \(str.trimmingCharacters(in: .whitespacesAndNewlines))")
            }
        }
        
        stderrPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if !data.isEmpty, let str = String(data: data, encoding: .utf8) {
                print("[Backend STDERR] \(str.trimmingCharacters(in: .whitespacesAndNewlines))")
            }
        }
        
        do {
            try proc.run()
            self.process = proc
            print("Successfully launched backend process from path: \(path)")
            self.startPingTimer()
        } catch {
            self.errorMessage = "Failed to launch backend: \(error.localizedDescription)"
        }
    }
    
    func terminateBackend() {
        pingTimer?.invalidate()
        pingTimer = nil
        
        if let proc = process, proc.isRunning {
            proc.terminate()
            proc.waitUntilExit()
            print("Backend process terminated.")
        }
    }
    
    private func startPingTimer() {
        pingTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            self?.checkHealth()
        }
    }
    
    private func checkHealth() {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/health") else { return }
        
        var request = URLRequest(url: url)
        request.timeoutInterval = 0.4
        
        let task = URLSession.shared.dataTask(with: request) { [weak self] _, response, error in
            guard let self = self else { return }
            if error == nil, let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                DispatchQueue.main.async {
                    if !self.isBackendReady {
                        self.isBackendReady = true
                        self.pingTimer?.invalidate()
                        self.pingTimer = nil
                        print("Backend health check passed! Web UI is ready.")
                    }
                }
            }
        }
        task.resume()
    }
}
