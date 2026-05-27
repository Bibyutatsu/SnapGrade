import SwiftUI

struct MainView: View {
    @ObservedObject var processManager: ProcessManager
    @State private var showCLIOnboarding = false

    // State for first-time model setup
    @State private var showModelSetup = false
    @State private var setupProgress: Double = 0.0
    @State private var setupStatusText: String = "Initializing..."
    @State private var setupError: String? = nil
    @State private var lineBuffer = ""
    @State private var completedModels = 0
    private let totalModels = 12

    var body: some View {
        ZStack {
            // Background color matches SnapGrade Film Lab theme
            Color(red: 0.04, green: 0.035, blue: 0.027)
                .ignoresSafeArea()

            if showModelSetup {
                ModelSetupView(
                    progress: setupProgress,
                    statusText: setupStatusText,
                    error: setupError,
                    onRetry: {
                        startModelSetup()
                    }
                )
                .transition(.opacity)
            } else if processManager.isBackendReady {
                WebView(url: URL(string: "http://127.0.0.1:8765")!)
                    .transition(.opacity)
                    .onAppear {
                        // Show the CLI install prompt once, 2 s after the web UI loads.
                        let shown = UserDefaults.standard.bool(forKey: "sg.cliPromptShown")
                        let installed = FileManager.default.fileExists(atPath: "/usr/local/bin/snapgrade")
                        if !shown && !installed {
                            DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                                showCLIOnboarding = true
                            }
                        }
                    }
            } else {
                VStack(spacing: 24) {
                    if let error = processManager.errorMessage {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.system(size: 44))
                            .foregroundColor(Color(red: 0.88, green: 0.29, blue: 0.17)) // c-danger

                        Text("Launch Error")
                            .font(.headline)
                            .foregroundColor(.white)

                        Text(error)
                            .font(.footnote)
                            .multilineTextAlignment(.center)
                            .foregroundColor(.gray)
                            .frame(maxWidth: 320)
                    } else {
                        // Custom spinner matching Film Lab theme
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: Color(red: 0.76, green: 0.27, blue: 0.06))) // c-accent
                            .scaleEffect(1.5)

                        VStack(spacing: 6) {
                            Text("SNAPGRADE")
                                .font(.system(size: 20, weight: .bold, design: .monospaced))
                                .tracking(4)
                                .foregroundColor(.white)

                            Text("Loading your local library...")
                                .font(.system(size: 11, design: .monospaced))
                                .foregroundColor(Color(red: 0.72, green: 0.69, blue: 0.61)) // c-text2
                        }
                    }
                }
                .transition(.opacity)
            }

            // CLI onboarding overlay — floats centered over the web UI on first launch.
            if showCLIOnboarding {
                Color.black.opacity(0.45)
                    .ignoresSafeArea()
                    .transition(.opacity)
                CLIOnboardingView(
                    onInstall: {
                        UserDefaults.standard.set(true, forKey: "sg.cliPromptShown")
                        showCLIOnboarding = false
                        CommandLineInstaller.install()
                    },
                    onDismiss: {
                        UserDefaults.standard.set(true, forKey: "sg.cliPromptShown")
                        showCLIOnboarding = false
                    }
                )
                .transition(.opacity.combined(with: .scale(scale: 0.96)))
            }
        }
        .frame(minWidth: 1024, minHeight: 768)
        .animation(.easeOut(duration: 0.18), value: showCLIOnboarding)
        .animation(.easeOut(duration: 0.18), value: showModelSetup)
        .onAppear {
            checkSetupAndLaunch()
        }
    }

    private func checkSetupAndLaunch() {
        let setupCompleted = UserDefaults.standard.bool(forKey: "sg.modelsSetupCompleted")
        let modelsDir = NSHomeDirectory() + "/.snapgrade/models"
        let modelsDirExists = FileManager.default.fileExists(atPath: modelsDir)
        let files = try? FileManager.default.contentsOfDirectory(atPath: modelsDir)
        
        if setupCompleted && modelsDirExists && (files?.count ?? 0) >= 11 {
            processManager.startBackend()
        } else {
            showModelSetup = true
            startModelSetup()
        }
    }

    private func startModelSetup() {
        setupProgress = 0.0
        setupStatusText = "Checking model cache..."
        setupError = nil
        completedModels = 0
        lineBuffer = ""
        
        processManager.runSetup(
            onProgress: { output in
                lineBuffer += output
                while let lineEndIndex = lineBuffer.firstIndex(of: "\n") {
                    let line = String(lineBuffer[..<lineEndIndex]).trimmingCharacters(in: .whitespacesAndNewlines)
                    lineBuffer = String(lineBuffer[lineBuffer.index(after: lineEndIndex)...])
                    processSetupLine(line)
                }
            },
            onCompletion: { success, errorMsg in
                if success {
                    setupProgress = 1.0
                    setupStatusText = "Setup complete!"
                    UserDefaults.standard.set(true, forKey: "sg.modelsSetupCompleted")
                    showModelSetup = false
                    processManager.startBackend()
                } else {
                    setupError = errorMsg ?? "Unknown error occurred during setup."
                }
            }
        )
    }

    private func processSetupLine(_ line: String) {
        if line.contains("✓") || line.contains("✗") {
            completedModels += 1
            setupProgress = min(Double(completedModels) / Double(totalModels), 0.99)
        }
        
        if line.contains("downloading") {
            let modelName = line.replacingOccurrences(of: "downloading ", with: "")
                                .replacingOccurrences(of: "…", with: "")
            let friendlyName = friendlyModelName(modelName)
            setupStatusText = "Downloading \(friendlyName)..."
        }
    }

    private func friendlyModelName(_ name: String) -> String {
        switch name {
        case "u2netp_coreml":
            return "Salient Subject Detector"
        case "yolo26n_coreml":
            return "Object Detector"
        case "yunet":
            return "Face Detector"
        case "face_landmarker":
            return "Face Landmark & Expression"
        case "depth_coreml":
            return "Depth Estimator"
        case "hyperiqa":
            return "Quality Assessment"
        case "topiq":
            return "Alternative Quality"
        case "nima":
            return "Aesthetic Scorer"
        case "places365":
            return "Scene Classifier"
        case "places365_labels":
            return "Scene Labels"
        case "mobileclip_image":
            return "Semantic Search (Image)"
        case "mobileclip_text":
            return "Semantic Search (Text)"
        default:
            return name
        }
    }
}
