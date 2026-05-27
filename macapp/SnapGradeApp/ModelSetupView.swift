import SwiftUI

struct ModelSetupView: View {
    var progress: Double
    var statusText: String
    var error: String?
    var onRetry: () -> Void
    
    var body: some View {
        VStack(spacing: 36) {
            VStack(spacing: 8) {
                Text("SNAPGRADE")
                    .font(.system(size: 24, weight: .bold, design: .monospaced))
                    .tracking(6)
                    .foregroundColor(.white)
                
                Text("FIRST-TIME SETUP")
                    .font(.system(size: 11, weight: .medium, design: .monospaced))
                    .tracking(2)
                    .foregroundColor(Color(red: 0.76, green: 0.27, blue: 0.06))
            }
            
            VStack(spacing: 20) {
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 64))
                    .foregroundColor(Color(red: 0.76, green: 0.27, blue: 0.06))
                
                Text("Downloading Model Weights")
                    .font(.system(size: 18, weight: .semibold, design: .monospaced))
                    .foregroundColor(.white)
                
                Text("SnapGrade runs all computer vision models locally on your Mac's Neural Engine. We need to download the required weights (~250MB) to ~/.snapgrade/models/ to begin.")
                    .font(.system(size: 12))
                    .foregroundColor(Color(red: 0.72, green: 0.69, blue: 0.61))
                    .multilineTextAlignment(.center)
                    .lineSpacing(4)
                    .frame(maxWidth: 440)
            }
            
            if let errorMsg = error {
                VStack(spacing: 20) {
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundColor(Color(red: 0.88, green: 0.29, blue: 0.17))
                        Text("Download Failed")
                            .font(.system(size: 13, weight: .bold, design: .monospaced))
                            .foregroundColor(.white)
                    }
                    
                    Text(errorMsg)
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Color(red: 0.88, green: 0.29, blue: 0.17))
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 440)
                    
                    HStack(spacing: 16) {
                        Button("Quit") {
                            NSApplication.shared.terminate(nil)
                        }
                        .buttonStyle(SGGhostButtonStyle())
                        
                        Button("Retry") {
                            onRetry()
                        }
                        .buttonStyle(SGPrimaryButtonStyle())
                    }
                }
                .padding(.top, 8)
            } else {
                VStack(spacing: 14) {
                    SGProgressBar(value: progress)
                        .frame(width: 360)
                    
                    HStack {
                        Text(statusText)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundColor(Color(red: 0.72, green: 0.69, blue: 0.61))
                        
                        Spacer()
                        
                        Text("\(Int(progress * 100))%")
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .foregroundColor(.white)
                    }
                    .frame(width: 360)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.04, green: 0.035, blue: 0.027))
    }
}

struct SGProgressBar: View {
    var value: Double
    
    var body: some View {
        GeometryReader { geometry in
            ZStack(alignment: .leading) {
                Rectangle().frame(width: geometry.size.width, height: 6)
                    .opacity(0.15)
                    .foregroundColor(Color(red: 0.72, green: 0.69, blue: 0.61))
                
                Rectangle().frame(width: min(CGFloat(self.value) * geometry.size.width, geometry.size.width), height: 6)
                    .foregroundColor(Color(red: 0.76, green: 0.27, blue: 0.06))
                    .animation(.linear(duration: 0.2), value: value)
            }
            .cornerRadius(3)
        }
        .frame(height: 6)
    }
}
