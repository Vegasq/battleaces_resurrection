using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

internal static class DesktopShortcut {
    internal static string Name(bool server) {
        return server ? "Battle Aces Server.lnk" : "Battle Aces Resurrection.lnk";
    }

    static string Marker(bool server) {
        return server ? "Battle Aces Resurrection server shortcut" : "Battle Aces Resurrection client shortcut";
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
        string path = Path.Combine(directory, Name(server));
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
                if (description != Marker(server))
                    throw new IOException("An unrelated desktop shortcut with the same name was preserved.");
            }
            Set(link, "TargetPath", launcher);
            Set(link, "WorkingDirectory", Path.GetDirectoryName(launcher));
            Set(link, "IconLocation", Path.Combine(Path.GetDirectoryName(launcher), server ? "Start Server.exe" : "Battle Aces.exe") + ",0");
            Set(link, "Description", Marker(server));
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
