using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading;

internal static class AcsBackgroundHost
{
    private static string Quote(string value)
    {
        if (value.Length > 0 && value.IndexOfAny(new char[] { ' ', '\t', '\n', '\v', '"' }) < 0)
            return value;
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value)
        {
            if (c == '\\') { slashes++; continue; }
            if (c == '"')
            {
                result.Append('\\', slashes * 2 + 1);
                result.Append(c);
            }
            else
            {
                result.Append('\\', slashes);
                result.Append(c);
            }
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        result.Append('"');
        return result.ToString();
    }

    [STAThread]
    private static int Main(string[] args)
    {
        try
        {
            if (args.Length < 2) return 64;
            string wsl = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "wsl.exe");
            if (!String.Equals(Path.GetFullPath(args[0]), wsl, StringComparison.OrdinalIgnoreCase)) return 64;
            StringBuilder arguments = new StringBuilder();
            for (int i = 1; i < args.Length; i++)
            {
                if (i > 1) arguments.Append(' ');
                arguments.Append(Quote(args[i]));
            }
            ProcessStartInfo start = new ProcessStartInfo(wsl, arguments.ToString());
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.RedirectStandardInput = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            return RunWithRetry(delegate { return RunOnce(start); },
                delegate { Thread.Sleep(TimeSpan.FromSeconds(30)); });
        }
        catch { return 70; }
    }

    private static int RunWithRetry(Func<int> run, Action delay)
    {
        // Scheduler success/failure classification differs between Windows
        // installations. Keep the owner task alive across failed WSL launches.
        // A successful exit includes the owner's explicit startup disable.
        while (true)
        {
            if (run() == 0) return 0;
            delay();
        }
    }

    private static int RunOnce(ProcessStartInfo start)
    {
        try
        {
            using (Process process = new Process())
            {
                process.StartInfo = start;
                process.OutputDataReceived += delegate { };
                process.ErrorDataReceived += delegate { };
                if (!process.Start()) return 70;
                process.StandardInput.Close();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();
                process.WaitForExit();
                return process.ExitCode;
            }
        }
        catch { return 70; }
    }
}
