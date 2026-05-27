import SwiftUI
import Foundation

/// Shows a one-time prompt (after the web UI loads) offering to install the
/// `snapgrade` command-line tool into /usr/local/bin.
struct CLIOnboardingView: View {
    let onInstall: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                Image(systemName: "terminal")
                    .font(.system(size: 28))
                    .foregroundColor(Color(red: 0.76, green: 0.27, blue: 0.06))
                VStack(alignment: .leading, spacing: 3) {
                    Text("Install Command Line Tool?")
                        .font(.system(size: 14, weight: .semibold, design: .monospaced))
                        .foregroundColor(.white)
                    Text("snapgrade → /usr/local/bin/snapgrade")
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundColor(Color(red: 0.72, green: 0.69, blue: 0.61))
                }
            }

            Text("Run `snapgrade analyze`, `snapgrade serve`, and `snapgrade setup` directly from the terminal without opening the app. Admin password may be required.")
                .font(.system(size: 11))
                .foregroundColor(Color(red: 0.72, green: 0.69, blue: 0.61))
                .lineSpacing(3)

            HStack(spacing: 10) {
                Button("Not Now") { onDismiss() }
                    .buttonStyle(SGGhostButtonStyle())

                Button("Install") { onInstall() }
                    .buttonStyle(SGPrimaryButtonStyle())
            }
        }
        .padding(22)
        .frame(width: 380)
        .background(Color(red: 0.09, green: 0.074, blue: 0.059))
        .overlay(
            RoundedRectangle(cornerRadius: 0)
                .stroke(Color(red: 0.16, green: 0.145, blue: 0.125), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.6), radius: 24, x: 0, y: 8)
    }
}

struct SGPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 10, weight: .medium, design: .monospaced))
            .tracking(1.5)
            .textCase(.uppercase)
            .padding(.horizontal, 18)
            .padding(.vertical, 8)
            .foregroundColor(Color(red: 0.76, green: 0.27, blue: 0.06))
            .overlay(
                RoundedRectangle(cornerRadius: 0)
                    .stroke(Color(red: 0.76, green: 0.27, blue: 0.06), lineWidth: 1)
            )
            .background(
                configuration.isPressed
                    ? Color(red: 0.76, green: 0.27, blue: 0.06).opacity(0.12)
                    : Color.clear
            )
    }
}

struct SGGhostButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 10, weight: .medium, design: .monospaced))
            .tracking(1.5)
            .textCase(.uppercase)
            .padding(.horizontal, 18)
            .padding(.vertical, 8)
            .foregroundColor(Color(red: 0.72, green: 0.69, blue: 0.61))
            .overlay(
                RoundedRectangle(cornerRadius: 0)
                    .stroke(Color(red: 0.42, green: 0.39, blue: 0.34), lineWidth: 1)
            )
            .background(configuration.isPressed ? Color.white.opacity(0.04) : Color.clear)
    }
}
