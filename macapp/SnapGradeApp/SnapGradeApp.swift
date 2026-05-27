import SwiftUI

@main
struct SnapGradeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var processManager = ProcessManager()
    
    var body: some Scene {
        WindowGroup {
            MainView(processManager: processManager)
                .onAppear {
                    // Save reference to process manager in delegate so it can shut down on exit
                    appDelegate.processManager = processManager
                }
        }
        .windowStyle(.hiddenTitleBar)
        .windowToolbarStyle(.unifiedCompact)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("Install Command Line Tool...") {
                    CommandLineInstaller.install()
                }
            }
        }
    }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    var processManager: ProcessManager?
    
    func applicationWillTerminate(_ notification: Notification) {
        print("Application is terminating. Cleaning up sidecar process...")
        processManager?.terminateBackend()
    }
}
