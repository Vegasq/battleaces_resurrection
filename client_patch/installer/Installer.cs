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
#if SERVER_INSTALLER
    static readonly bool Server = true;
#else
    static readonly bool Server = false;
#endif
    readonly TextBox game = new TextBox(), address = new TextBox(), playerName = new TextBox();
    readonly Button browse = new Button(), install = new Button(), reset = new Button(), uninstall = new Button();
    readonly Label status = new Label();
    readonly ProgressBar progress = new ProgressBar();
    readonly BackgroundWorker worker = new BackgroundWorker();
    readonly Timer timer = new Timer();
    DateTime started;
    string selectedGame, selectedAddress, selectedPlayerName;
    bool resetRequested, uninstallRequested;
    bool playerNameEdited, loadingPlayerName;
    readonly string smokeReport;

    Installer(string smoke) {
        smokeReport = smoke;
        Text = "Battle Aces Resurrection - Install";
        ClientSize = new Size(720, Server ? 405 : 465); StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false;
        AutoScaleMode = AutoScaleMode.Dpi; Font = new Font("Segoe UI", 10);
        BackColor = Color.FromArgb(246, 248, 251);
        AddLabel(Server ? "Install Battle Aces Server" : "Install Battle Aces Resurrection", 22, 20, 675, 40).Font = new Font("Segoe UI", 19, FontStyle.Bold);
        AddLabel(Server ? "Choose your game and an empty folder for the server." : "Choose your game folder, server IP and player name.", 24, 67, 670, 28);
        AddLabel("Game folder", 24, 118, 120, 28);
        game.SetBounds(148, 114, 430, 28); Controls.Add(game);
        browse.Text = "Browse..."; browse.SetBounds(590, 110, 106, 35); Controls.Add(browse);
        AddLabel(Server ? "Server folder" : "Server IP", 24, 170, 120, 28);
        address.SetBounds(148, 166, 548, 28); address.MaxLength = 253; Controls.Add(address);
        if (Server) {
            address.Width = 430;
            var destination = new Button(); destination.Text = "Browse..."; destination.SetBounds(590, 162, 106, 35); Controls.Add(destination);
            destination.Click += delegate { if (worker.IsBusy) return; using (var dialog = new FolderBrowserDialog()) {
                dialog.Description = "Choose an empty folder for the dedicated server";
                if (dialog.ShowDialog(this) == DialogResult.OK) address.Text = dialog.SelectedPath;
            }};
        }
        playerName.Visible = !Server;
        if (!Server) {
            AddLabel("Player name", 24, 222, 120, 28);
            playerName.SetBounds(148, 218, 548, 28); playerName.MaxLength = 64;
            playerName.Text = PlayerName.Default(); Controls.Add(playerName);
            playerName.TextChanged += delegate { if (!loadingPlayerName) playerNameEdited = true; };
            game.TextChanged += delegate { RefreshPlayerName(); };
        }
        AddLabel(Server ? "Imports game data locally. Creates Start Server.exe; no game files ship." : "Leave server IP blank for offline play. Player name: 1-32 characters.", 148, Server ? 202 : 254, 548, 38);
        int actions = Server ? 247 : 305;
        install.Text = "Install / Update"; install.SetBounds(24, actions, 178, 39); Controls.Add(install);
        reset.Text = "Reset selected deck"; reset.SetBounds(220, actions, 195, 39); Controls.Add(reset);
        reset.Visible = !Server;
        uninstall.Text = "Uninstall client patch"; uninstall.SetBounds(435,actions,261,39); uninstall.Visible = !Server; Controls.Add(uninstall);
        progress.SetBounds(24,Server ? 299 : 357,672,16);
        progress.Style = ProgressBarStyle.Marquee; progress.Visible = false; Controls.Add(progress);
        status.SetBounds(24, Server ? 331 : 389, 672, 65); status.Text = Server ? "Creates Start Server.exe. The source game folder stays unchanged." : "Creates Start Battle Aces.cmd in your game folder."; Controls.Add(status);
        browse.Click += delegate {
            using (var dialog = new FolderBrowserDialog()) {
                dialog.Description = "Choose the folder containing Battle Aces.exe";
                if (dialog.ShowDialog(this) == DialogResult.OK) game.Text = dialog.SelectedPath;
            }
        };
        EventHandler begin = delegate(object sender, EventArgs e) {
            if (worker.IsBusy) return;
            if (!File.Exists(Path.Combine(game.Text, "Battle Aces.exe"))) { status.Text = "Choose the folder containing Battle Aces.exe."; return; }
            resetRequested = !Server && sender == reset;
            uninstallRequested = !Server && sender == uninstall;
            if (resetRequested && MessageBox.Show(this, "Close the game first. Reset only the selected deck to the original starter deck? Saved decks, cosmetics and options stay unchanged. A settings backup is kept.", "Reset selected deck", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
            if (uninstallRequested && MessageBox.Show(this, "Close the game first. Restore the original game files and remove the Resurrection launcher and helper? Saves, configuration, recovery backups and cached runtime will be kept.", "Uninstall client patch", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return;
            selectedGame = game.Text; selectedAddress = address.Text.Trim();
            selectedPlayerName = playerName.Text;
            game.Enabled = address.Enabled = playerName.Enabled = browse.Enabled = install.Enabled = reset.Enabled = uninstall.Enabled = false;
            progress.Visible = true; started = DateTime.UtcNow; timer.Start();
            status.Text = "Preparing installation..."; worker.RunWorkerAsync();
        };
        install.Click += begin; reset.Click += begin; uninstall.Click += begin;
        worker.DoWork += RunInstall;
        worker.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs e) {
            timer.Stop(); Text = "Battle Aces Resurrection - Install"; progress.Visible = false;
            game.Enabled = address.Enabled = playerName.Enabled = browse.Enabled = install.Enabled = reset.Enabled = uninstall.Enabled = true;
            status.Text = e.Error == null ? (Server ? "Installed. Open Start Server.exe in your server folder to host." : uninstallRequested ? "Client patch uninstalled. Original game restored; saves and recovery files kept." : resetRequested ? "Deck reset. Start Battle Aces.cmd will load the original starter deck." : "Installed. Open Start Battle Aces.cmd in your game folder to play.") : e.Error.Message;
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
                    player_name_field_visible = playerName.Visible, player_name_nonempty = !String.IsNullOrWhiteSpace(playerName.Text),
                    account_default_used = !Server && !playerNameEdited && playerName.Text == PlayerName.Default(),
                    install_button_visible = install.Visible, reset_button_visible = reset.Visible,
                    uninstall_button_visible = uninstall.Visible, server_installer = Server, powershell_used = false,
                    progress_control_attached = progress.Parent == this && Controls.Contains(progress)
                })); close.Dispose(); Close();
            };
            close.Start();
        };
    }

    Label AddLabel(string text, int x, int y, int width, int height) {
        var label = new Label(); label.Text = text; label.SetBounds(x,y,width,height); Controls.Add(label); return label;
    }

    void RefreshPlayerName() {
        if (Server || playerNameEdited) return;
        string value = PlayerName.Default();
        try {
            string path = Path.Combine(game.Text, ".battleaces-resurrection", "client-config.json");
            if (File.Exists(path) && new FileInfo(path).Length <= 32768) {
                var saved = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(path));
                object name;
                if (saved.TryGetValue("display_name", out name) && name is string) value = (string)name;
            }
        } catch (Exception) { /* Backend validates config before writing; this is only a read-only preview. */ }
        loadingPlayerName = true;
        try { playerName.Text = value; } finally { loadingPlayerName = false; }
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
            return Path.Combine(root, Server ? "battleaces-server-win64" : "battleaces-client-win64");
        }
    }

    void RunInstall(object sender, DoWorkEventArgs args) {
        string package = PackageRoot(), request = Path.GetTempFileName();
        try {
            var values = new Dictionary<string,string> {
                {"game_directory", selectedGame}, {Server ? "server_directory" : "server_host", selectedAddress}
            };
            if (!Server && !resetRequested && !uninstallRequested) values.Add("display_name", selectedPlayerName);
            File.WriteAllText(request, new JavaScriptSerializer().Serialize(values), new UTF8Encoding(false));
            var info = new ProcessStartInfo(Path.Combine(package, "program", "runtime", "python.exe"));
            info.Arguments = "-I -B -m " + (Server ? "tools.package_server install-server" : "tools.package_client " + (uninstallRequested ? "uninstall-game" : resetRequested ? "reset-deck" : "install-game")) + " --request " + Quote(request);
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
            if (args.Length == 3 && args[0] == "--name-smoke") {
                var serializer = new JavaScriptSerializer();
                string[] inputs = serializer.Deserialize<string[]>(File.ReadAllText(args[1]));
                File.WriteAllText(args[2], serializer.Serialize(Array.ConvertAll(inputs, PlayerName.Clean))); return;
            }
            if (args.Length == 3 && args[0] == "--ui-name-smoke") {
                var serializer = new JavaScriptSerializer();
                var input = serializer.Deserialize<Dictionary<string,string>>(File.ReadAllText(args[1]));
                using (var form = new Installer(null)) {
                    form.game.Text = input["game_directory"];
                    string saved = form.playerName.Text;
                    form.game.Text = input["other_game_directory"];
                    string other = form.playerName.Text;
                    form.playerName.Text = input["chosen_name"];
                    form.game.Text = input["game_directory"];
                    form.Show(); form.Refresh();
                    File.WriteAllText(args[2], serializer.Serialize(new {
                        shown = form.Visible, saved_name = saved, other_saved_name = other, chosen_name = form.playerName.Text,
                        player_name_visible = form.playerName.Visible, edited_name_retained = form.playerNameEdited
                    })); form.Close();
                }
                return;
            }
            if (args.Length == 2 && args[0] == "--verify-payload") {
                string package = PackageRoot();
                var info = new ProcessStartInfo(Path.Combine(package, "program", "runtime", "python.exe"));
                info.Arguments = "-I -B -m " + (Server ? "tools.package_server" : "tools.package_client") + " verify"; info.UseShellExecute = false; info.CreateNoWindow = true;
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
                    form.game.Text = @"D:\Battle Aces"; form.address.Text = Server ? @"D:\Battle Aces Server" : "192.168.1.25";
                    if (!Server) form.playerName.Text = "Commander";
                    form.Show(); form.Refresh();
                    using (var bitmap = new Bitmap(form.Width, form.Height)) { form.DrawToBitmap(bitmap, new Rectangle(0,0,form.Width,form.Height)); bitmap.Save(args[1]); }
                    form.Close();
                } else Application.Run(form);
            }
        } catch (Exception error) { MessageBox.Show(error.Message, "Battle Aces Setup", MessageBoxButtons.OK, MessageBoxIcon.Error); Environment.ExitCode = 1; }
    }
}
