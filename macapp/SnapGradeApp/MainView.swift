import SwiftUI

struct MainView: View {
    @ObservedObject var processManager: ProcessManager
    
    var body: some View {
        ZStack {
            // Background color matches SnapGrade Film Lab theme
            Color(red: 0.04, green: 0.035, blue: 0.027)
                .ignoresSafeArea()
            
            if processManager.isBackendReady {
                WebView(url: URL(string: "http://127.0.0.1:8765")!)
                    .transition(.opacity)
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
        }
        .frame(minWidth: 1024, minHeight: 768)
    }
}
