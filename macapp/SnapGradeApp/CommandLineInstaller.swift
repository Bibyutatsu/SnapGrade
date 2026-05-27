import Foundation
import Cocoa

struct CommandLineInstaller {
    static func install() {
        let fileManager = FileManager.default
        let binDirectory = "/usr/local/bin"
        let symlinkPath = "\(binDirectory)/snapgrade"
        
        // Find the packaged binary inside the App bundle Resources directory
        guard let backendPath = Bundle.main.path(forResource: "snapgrade_backend/snapgrade_backend", ofType: nil) else {
            print("Error: snapgrade_backend not found in bundle resources.")
            return
        }
        
        // 1. Ensure /usr/local/bin exists
        if !fileManager.fileExists(atPath: binDirectory) {
            do {
                try fileManager.createDirectory(atPath: binDirectory, withIntermediateDirectories: true)
            } catch {
                print("Failed to create /usr/local/bin: \(error.localizedDescription)")
                // If creation fails due to permissions, the AppleScript fallback below will handle it
            }
        }
        
        // 2. Check if symlink exists
        if fileManager.fileExists(atPath: symlinkPath) {
            // Check if it already points to the correct path
            if let destination = try? fileManager.destinationOfSymbolicLink(atPath: symlinkPath), destination == backendPath {
                alertUser(title: "Already Installed", message: "The 'snapgrade' command line tool is already installed and up to date.")
                return
            }
            
            // Delete old symlink first
            do {
                try fileManager.removeItem(atPath: symlinkPath)
            } catch {
                print("Failed to remove old symlink: \(error.localizedDescription)")
            }
        }
        
        // 3. Try to create the symlink silently
        do {
            try fileManager.createSymbolicLink(atPath: symlinkPath, withDestinationPath: backendPath)
            alertUser(title: "Success", message: "Successfully installed 'snapgrade' command line tool to /usr/local/bin/snapgrade.")
        } catch {
            // 4. Fallback to AppleScript with administrative privileges
            let script = "do shell script \"mkdir -p '\(binDirectory)' && ln -sf '\(backendPath)' '\(symlinkPath)'\" with administrator privileges"
            let appleScript = NSAppleScript(source: script)
            var errorInfo: NSDictionary?
            appleScript?.executeAndReturnError(&errorInfo)
            
            if let err = errorInfo {
                print("Admin installation failed: \(err)")
                alertUser(title: "Installation Failed", message: "Failed to install the CLI tool. Permission was denied.")
            } else {
                alertUser(title: "Success", message: "Successfully installed 'snapgrade' command line tool to /usr/local/bin/snapgrade.")
            }
        }
    }
    
    private static func alertUser(title: String, message: String) {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.messageText = title
            alert.informativeText = message
            alert.alertStyle = .informational
            alert.addButton(withTitle: "OK")
            alert.runModal()
        }
    }
}
