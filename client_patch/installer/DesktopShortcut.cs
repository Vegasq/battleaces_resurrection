using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;

internal static class DesktopShortcut {
    internal static bool IsPredictionLauncher(string launcher, bool server) {
        return !server && String.Equals(Path.GetFileName(launcher), "Start Prediction Client.cmd", StringComparison.OrdinalIgnoreCase);
    }

    internal static string Name(bool server, string launcher = null) {
        return server ? "Battle Aces Server.lnk" : IsPredictionLauncher(launcher, server) ? "Battle Aces Prediction Test.lnk" : "Battle Aces Resurrection.lnk";
    }

    static string Marker(bool server, string launcher) {
        return server ? "Battle Aces Resurrection server shortcut" : IsPredictionLauncher(launcher, server) ? "Battle Aces Prediction Test client shortcut" : "Battle Aces Resurrection client shortcut";
    }

    internal static string SuccessMessage(string launcher, bool server) {
        return "Installed. " + Path.GetFileNameWithoutExtension(Name(server, launcher)) + " shortcut created on your desktop.";
    }

    internal static string InstalledLauncher(string output, string directory, bool server) {
        const string invalid = "The installer returned an invalid installed launcher.";
        if (String.IsNullOrWhiteSpace(output) || output.Length > 131072) throw new IOException(invalid);
        var serializer = new JavaScriptSerializer { MaxJsonLength = 131072 };
        Dictionary<string, object> envelope;
        try { envelope = serializer.Deserialize<Dictionary<string, object>>(output); }
        catch (Exception error) { throw new IOException(invalid, error); }
        object ok, result, installed, value;
        if (envelope == null || !envelope.TryGetValue("ok", out ok) || !(ok is bool) || !(bool)ok ||
            !envelope.TryGetValue("result", out result)) throw new IOException(invalid);
        var fields = result as Dictionary<string, object>;
        if (fields == null || !fields.TryGetValue("installed", out installed) || !(installed is bool) || !(bool)installed ||
            !fields.TryGetValue("launcher", out value) || !(value is string)) throw new IOException(invalid);
        string launcher = (string)value;
        if (String.IsNullOrWhiteSpace(launcher) || !Path.IsPathRooted(launcher)) throw new IOException(invalid);
        string target = Path.GetFullPath(launcher), name = Path.GetFileName(target);
        bool allowed = server ? String.Equals(name, "Start Server.exe", StringComparison.OrdinalIgnoreCase) :
            String.Equals(name, "Start Battle Aces.cmd", StringComparison.OrdinalIgnoreCase) || IsPredictionLauncher(target, false);
        string expected = Path.GetFullPath(Path.Combine(Path.GetFullPath(directory), name));
        if (!allowed || !String.Equals(target, expected, StringComparison.OrdinalIgnoreCase) || !File.Exists(target) ||
            (File.GetAttributes(target) & FileAttributes.ReparsePoint) != 0) throw new IOException(invalid);
        return target;
    }

    static object Member(object value, string name, BindingFlags action, object[] arguments) {
        return value.GetType().InvokeMember(name, action, null, value, arguments);
    }

    static void Set(object value, string name, object item) {
        Member(value, name, BindingFlags.SetProperty, new object[] { item });
    }

    internal static string Create(string directory, string launcher, bool server) {
        if (String.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory))
            throw new IOException("The desktop folder is unavailable.");
        launcher = Path.GetFullPath(launcher);
        if (!File.Exists(launcher)) throw new IOException("The installed launcher is missing.");
        string path = Path.Combine(directory, Name(server, launcher));
        Type kind = Type.GetTypeFromProgID("WScript.Shell");
        if (kind == null) throw new IOException("Windows shortcut support is unavailable.");
        object shell = null, link = null;
        try {
            shell = Activator.CreateInstance(kind);
            link = Member(shell, "CreateShortcut", BindingFlags.InvokeMethod, new object[] { path });
            if (File.Exists(path)) {
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("An unrelated desktop shortcut with the same name was preserved.");
                string description = (string)Member(link, "Description", BindingFlags.GetProperty, null);
                if (description != Marker(server, launcher))
                    throw new IOException("An unrelated desktop shortcut with the same name was preserved.");
            }
            Set(link, "TargetPath", launcher);
            Set(link, "WorkingDirectory", Path.GetDirectoryName(launcher));
            Set(link, "IconLocation", Path.Combine(Path.GetDirectoryName(launcher), server ? "Start Server.exe" : "Battle Aces.exe") + ",0");
            Set(link, "Description", Marker(server, launcher));
            Member(link, "Save", BindingFlags.InvokeMethod, null);
            if (!File.Exists(path)) throw new IOException("Windows did not save the desktop shortcut.");
            return path;
        } finally {
            if (link != null && Marshal.IsComObject(link)) Marshal.FinalReleaseComObject(link);
            if (shell != null && Marshal.IsComObject(shell)) Marshal.FinalReleaseComObject(shell);
        }
    }

    internal static string CreateOnDesktop(string launcher, bool server) {
        return Create(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), launcher, server);
    }
}

internal static class InstallerPayload {
    internal static string Root(string extracted, bool server) {
        if (server) return Path.Combine(extracted, "battleaces-server-win64");
        string selected = null;
        foreach (string name in new string[] { "battleaces-client-win64", "battleaces-client-prediction-private-win64" }) {
            string candidate = Path.Combine(extracted, name);
            if (!File.Exists(Path.Combine(candidate, "package-manifest.json")) ||
                !File.Exists(Path.Combine(candidate, "program", "runtime", "python.exe"))) continue;
            if (selected != null) throw new IOException("The installer payload contains multiple client packages.");
            selected = candidate;
        }
        if (selected == null) throw new IOException("The installer payload has no valid client package.");
        return selected;
    }
}
