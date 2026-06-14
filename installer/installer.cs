using System;
using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Windows.Forms;

class Program {
    [STAThread]
    static void Main(string[] args) {
        bool quiet = false;
        foreach (string arg in args) {
            if (arg.Equals("/quiet", StringComparison.OrdinalIgnoreCase) || 
                arg.Equals("/silent", StringComparison.OrdinalIgnoreCase) || 
                arg.Equals("/s", StringComparison.OrdinalIgnoreCase) ||
                arg.Equals("-q", StringComparison.OrdinalIgnoreCase)) {
                quiet = true;
            }
        }

        string logPath = Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? ".", "install.log");

        try {
            string tempDir = Path.Combine(Path.GetTempPath(), "AnkiOcclusionStaging_" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(tempDir);
            
            // Extract embedded resources
            ExtractResource("AnkiOcclusion.zip", Path.Combine(tempDir, "AnkiOcclusion.zip"));
            ExtractResource("install.ps1", Path.Combine(tempDir, "install.ps1"));
            
            // Run powershell script
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = "powershell.exe";
            psi.Arguments = string.Format("-NoProfile -ExecutionPolicy Bypass -File \"{0}\" -Quiet", Path.Combine(tempDir, "install.ps1"));
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            
            Process p = Process.Start(psi);
            string output = p.StandardOutput.ReadToEnd();
            string error = p.StandardError.ReadToEnd();
            p.WaitForExit();
            
            if (quiet) {
                File.WriteAllText(logPath, string.Format("ExitCode: {0}\nStdout:\n{1}\nStderr:\n{2}\n", p.ExitCode, output, error));
            }
            
            if (p.ExitCode != 0) {
                throw new Exception(string.Format("Installation script failed with exit code {0}.\nError: {1}", p.ExitCode, error));
            }
            
            if (!quiet) {
                MessageBox.Show("Anki Occlusion has been successfully installed!", "Anki Occlusion Setup", MessageBoxButtons.OK, MessageBoxIcon.Information);
            }
            
            // Clean up temp dir
            try { Directory.Delete(tempDir, true); } catch {}
        } catch (Exception ex) {
            if (!quiet) {
                MessageBox.Show("Error during installation:\n" + ex.Message, "Anki Occlusion Setup Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
            } else {
                File.AppendAllText(logPath, "\nEXCEPTION:\n" + ex.ToString());
                Console.Error.WriteLine("Error during installation: " + ex.Message);
            }
            Environment.Exit(1);
        }
    }
    
    static void ExtractResource(string resourceName, string outputPath) {
        using (Stream input = Assembly.GetExecutingAssembly().GetManifestResourceStream(resourceName)) {
            if (input == null) {
                throw new Exception("Resource not found: " + resourceName);
            }
            using (Stream output = File.Create(outputPath)) {
                input.CopyTo(output);
            }
        }
    }
}
