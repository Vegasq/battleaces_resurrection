using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// BA_RESURRECTION_NATIVE_INSTALLER_V1
internal sealed class Installer : Form {
    readonly TextBox game = new TextBox(), address = new TextBox();
    readonly Button browse = new Button(), install = new Button();
    readonly Label status = new Label();
    readonly ProgressBar progress = new ProgressBar();
    readonly BackgroundWorker worker = new BackgroundWorker();
    readonly Timer timer = new Timer();
    DateTime started;
    string selectedGame, selectedAddress;
    readonly string smokeReport;

    Installer(string smoke) {
        smokeReport = smoke;
        Text = "Battle Aces Resurrection - Install";
        ClientSize = new Size(720, 360); StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false;
        AutoScaleMode = AutoScaleMode.Dpi; Font = new Font("Segoe UI", 10);
        BackColor = Color.FromArgb(246, 248, 251);
        AddLabel("Install Battle Aces Resurrection", 22, 20, 675, 40).Font = new Font("Segoe UI", 19, FontStyle.Bold);
        AddLabel("Choose your game folder and enter the server IP.", 24, 67, 670, 28);
        AddLabel("Game folder", 24, 118, 120, 28);
        game.SetBounds(148, 114, 430, 28); Controls.Add(game);
        browse.Text = "Browse..."; browse.SetBounds(590, 110, 106, 35); Controls.Add(browse);
        AddLabel("Server IP", 24, 170, 120, 28);
        address.SetBounds(148, 166, 548, 28); address.MaxLength = 253; Controls.Add(address);
        AddLabel("Leave blank for offline play. You can edit the saved settings later.", 148, 202, 548, 30);
        install.Text = "Install / Update"; install.SetBounds(24, 247, 178, 39); Controls.Add(install);
        progress.SetBounds(220, 254, 476, 22); progress.Style = ProgressBarStyle.Marquee; progress.Visible = false;
        status.SetBounds(24, 303, 672, 50); status.Text = "Creates Start Battle Aces.cmd in your game folder."; Controls.Add(status);
        browse.Click += delegate {
            using (var dialog = new FolderBrowserDialog()) {
                dialog.Description = "Choose the folder containing Battle Aces.exe";
                if (dialog.ShowDialog(this) == DialogResult.OK) game.Text = dialog.SelectedPath;
            }
        };
        install.Click += delegate {
            if (worker.IsBusy) return;
            if (!File.Exists(Path.Combine(game.Text, "Battle Aces.exe"))) { status.Text = "Choose the folder containing Battle Aces.exe."; return; }
            selectedGame = game.Text; selectedAddress = address.Text.Trim();
            game.Enabled = address.Enabled = browse.Enabled = install.Enabled = false;
            progress.Visible = true; started = DateTime.UtcNow; timer.Start();
            status.Text = "Preparing installation..."; worker.RunWorkerAsync();
        };
        worker.DoWork += RunInstall;
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e) {
            timer.Stop(); Text = "Battle Aces Resurrection - Install"; progress.Visible = false;
            game.Enabled = address.Enabled = browse.Enabled = install.Enabled = true;
            status.Text = e.Error == null ? "Installed. Open Start Battle Aces.cmd in your game folder to play." : e.Error.Message;
            if (e.Error != null) MessageBox.Show(this, e.Error.Message, "Installation failed", MessageBoxButtons.OK, MessageBoxIcon.Error);
        };
        timer.Interval = 1000; timer.Tick += delegate { Text = "Battle Aces Resurrection - Installing (" + (int)(DateTime.UtcNow-started).TotalSeconds + "s)"; };
        FormClosing += delegate(object sender, FormClosingEventArgs e) { if (worker.IsBusy) { e.Cancel = true; status.Text = "Please wait for installation to finish."; } };
        if (smokeReport != null) Shown += delegate {
            var close = new Timer(); close.Interval = 400;
            close.Tick += delegate {
                close.Stop(); int fields = 0;
                foreach (Control control in Controls) if (control is TextBox && control.Visible && control.Enabled) fields++;
                File.WriteAllText(smokeReport, new JavaScriptSerializer().Serialize(new {
                    shown = Visible && Created && IsHandleCreated, editable_fields = fields,
                    game_field_visible = game.Visible, server_field_visible = address.Visible,
                    install_button_visible = install.Visible, powershell_used = false
                })); close.Dispose(); Close();
            };
            close.Start();
        };
    }

    Label AddLabel(string text, int x, int y, int width, int height) {
        var label = new Label(); label.Text = text; label.SetBounds(x,y,width,height); Controls.Add(label); return label;
    }

    static string Quote(string value) {
        var result = new StringBuilder("\""); int slashes = 0;
        foreach (char ch in value) {
            if (ch == '\\') { slashes++; continue; }
            result.Append('\\', ch == '"' ? slashes * 2 + 1 : slashes); slashes = 0; result.Append(ch);
        }
        result.Append('\\', slashes * 2); return result.Append('"').ToString();
    }

    static string PackageRoot() {
        string folder = AppDomain.CurrentDomain.BaseDirectory;
        using (Stream payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("BattleAces.Payload.zip")) {
            if (payload == null) {
                if (File.Exists(Path.Combine(folder, "program", "runtime", "python.exe"))) return folder;
                throw new Exception("Extract the complete installer ZIP, then run Install Battle Aces.exe.");
            }
            string root = Path.Combine(Path.GetTempPath(), "BattleAces-Setup-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            using (var archive = new ZipArchive(payload, ZipArchiveMode.Read)) {
                long total = 0;
                if (archive.Entries.Count > 2048) throw new Exception("Invalid installer payload.");
                foreach (ZipArchiveEntry entry in archive.Entries) {
                    total += entry.Length;
                    if (total > 128L*1024*1024 || entry.FullName.IndexOf('\\') >= 0) throw new Exception("Invalid installer payload.");
                    string path = Path.GetFullPath(Path.Combine(root, entry.FullName.Replace('/', Path.DirectorySeparatorChar)));
                    if (!path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || entry.FullName.IndexOf(':') >= 0) throw new Exception("Invalid installer payload path.");
                    Directory.CreateDirectory(Path.GetDirectoryName(path));
                    using (Stream input = entry.Open()) using (Stream output = new FileStream(path, FileMode.CreateNew)) input.CopyTo(output);
                }
            }
            return Path.Combine(root, "battleaces-client-win64");
        }
    }

    void RunInstall(object sender, DoWorkEventArgs args) {
        string package = PackageRoot(), request = Path.GetTempFileName();
        try {
            File.WriteAllText(request, new JavaScriptSerializer().Serialize(new Dictionary<string,string> {
                {"game_directory", selectedGame}, {"server_host", selectedAddress}
            }), new UTF8Encoding(false));
            var info = new ProcessStartInfo(Path.Combine(package, "program", "runtime", "python.exe"));
            info.Arguments = "-I -B -m tools.package_client install-game --request " + Quote(request);
            info.UseShellExecute = false; info.CreateNoWindow = true;
            info.RedirectStandardOutput = info.RedirectStandardError = true;
            using (var process = new Process()) {
                process.StartInfo = info;
                process.ErrorDataReceived += delegate(object source, DataReceivedEventArgs e) {
                    if (!String.IsNullOrWhiteSpace(e.Data) && IsHandleCreated) BeginInvoke((Action)delegate { status.Text = e.Data; });
                };
                process.Start(); process.BeginErrorReadLine();
                string output = process.StandardOutput.ReadToEnd(); process.WaitForExit();
                if (process.ExitCode != 0) {
                    string message = "Installation failed. Check the game folder and available disk space.";
                    try { var parsed = new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(output); if (parsed.ContainsKey("error")) message = (string)parsed["error"]; } catch { }
                    throw new Exception(message);
                }
            }
        } finally { File.Delete(request); }
    }

    [STAThread] static void Main(string[] args) {
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        try {
            if (args.Length == 2 && args[0] == "--verify-payload") {
                string package = PackageRoot();
                var info = new ProcessStartInfo(Path.Combine(package, "program", "runtime", "python.exe"));
                info.Arguments = "-I -B -m tools.package_client verify"; info.UseShellExecute = false; info.CreateNoWindow = true;
                info.RedirectStandardOutput = info.RedirectStandardError = true;
                using (var process = Process.Start(info)) {
                    string output = process.StandardOutput.ReadToEnd(), error = process.StandardError.ReadToEnd(); process.WaitForExit();
                    File.WriteAllText(args[1], new JavaScriptSerializer().Serialize(new {
                        verified = process.ExitCode == 0, package_root = package,
                        exit_code = process.ExitCode, stdout = output, stderr = error
                    })); Environment.ExitCode = process.ExitCode;
                }
                return;
            }
            string smoke = args.Length == 2 && args[0] == "--ui-smoke" ? args[1] : null;
            using (var form = new Installer(smoke)) {
                if (args.Length == 2 && args[0] == "--render-preview") {
                    form.game.Text = @"D:\Battle Aces"; form.address.Text = "192.168.1.25";
                    form.Show(); form.Refresh();
                    using (var bitmap = new Bitmap(form.Width, form.Height)) { form.DrawToBitmap(bitmap, new Rectangle(0,0,form.Width,form.Height)); bitmap.Save(args[1]); }
                    form.Close();
                } else Application.Run(form);
            }
        } catch (Exception error) { MessageBox.Show(error.Message, "Battle Aces Setup", MessageBoxButtons.OK, MessageBoxIcon.Error); Environment.ExitCode = 1; }
    }
}
