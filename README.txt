BATTLE ACES RESURRECTION
Windows x64 server and reversible client patch for Battle Aces build37822.

START HERE
  Work remaining:       docs/REMAINING_DELIVERY_PLAN.txt
  Release gates:        docs/RELEASE_ACCEPTANCE.txt
  Latest evidence:      docs/STATUS.txt
  Guides and references:docs/INDEX.txt
  Nick's requests:      DEV.txt (private/local; answers belong here)

CURRENT POSITION - 2026-10-24
The Windows release candidate works, including accepted physical LAN play and
startup. Final release qualification is still open. Published prerelease174 is
the current coherent client/server pair:version0.3.0-rc1.6,recipe23/helper169,
including171's disabled Korean login/compliance flow. Download both installers:
https://github.com/Vegasq/battleaces_resurrection/releases/tag/v0.3.0-rc1.6
Both public downloads are hash-verified. Exact identities and tested scope:
docs/coherent-candidate174.txt. Earlier166/manual copies remain frozen.

Nick has confirmed N2/LAN, N5/download-install, N9/desktop pipe and N10/protected
recovery PASS. N7's remaining visible portrait/host/save details are unreported.
Complete analytics/report removal, the remaining mode/catalog/storage matrix,
service/clean-PC deployment, Internet/capacity and final freeze remain open.

PLAY OR HOST
Experimental Linux/Wine hosting is available through tools/linux_server.py,
which bypasses the Windows installer UI using its verified bundled backend.
Linux host guide:docs/linux-server-quickstart.txt. Scoped evidence:docs/linux-host175.txt.
For a copied Windows host,the guide covers relocate/prepare-prefix commands,
which preserve the copied TLS identity/player data and select a persistent prefix.
Client CLI:tools/linux_client.py installs/checks in headless Wine without opening
the game. Run start separately. Guide:docs/linux-client-quickstart.txt.

Use the native client installer,then Start Battle Aces.cmd INSIDE the selected
game folder. Setup asks for game folder,server IP and editable Player name;
existing profiles/names are preserved. A blank server address permits local AI.
The installed runtime is independent of the downloaded installer folder.
Player guide: docs/windows-client-quickstart.txt.

The native server installer imports your local game data through an independent
working copy and creates Start Server.exe. The selected source game stays intact.
Start Server.exe hosts;Ctrl+C stops it. Host guide: docs/windows-server-quickstart.txt.
RC mode uses TLS encryption with certificate verification disabled and open
admission,as requested. Optional verified CA/invite mode remains available.
No original game assets are distributed. Internet release acceptance is pending.

IMPLEMENTED CAPABILITIES
- Server dashboard175:online players,active games and persistent match history.
  Included in source;published174 installers predate it. docs/server-dashboard175.txt.
- Local Try Deck and public1v1/2v2/2vAI with local fallback;online queues retain
  available humans and fill missing public seats after30seconds. Custom is human-only.
- Custom presence/invites,results/Continue and same-connection rematches.
- Editable names,selected decks,107 installed cosmetics/17slots,portraits and
  persistent Easy/Normal/Hard practice settings,with scoped native evidence.
- Isolated native simulation workers,persistent host profiles,TLS,backup/restore,
  native installers,selected-deck reset and reversible client uninstall.
Implementation is not blanket acceptance. The roadmap identifies remaining gates.

SOURCE LAYOUT
  server/                 Python coordinator,protocol,native workers and host
  client_patch/src/       C++ helper
  client_patch/patcher/   exact-build recipes and reversible installer
  client_patch/launcher/  client configuration and launchers
  client_patch/transport/ verified TLS/authentication parent
  tools/                  import,packaging,diagnostics and publication audit
  tests/                  source tests,including explicitly gated native cases
  docs/                   current plan,guides,topic references and history/
  local/,build/,dist/     ignored inputs,artifacts and retained evidence

DEVELOPER CHECKS AND BUILDS
Read AGENTS.md before project work. Python source checks target3.12 and3.14.8:
  python -m unittest discover -s tests -v
  python -m tools.audit_repository --history
The audit reads the Git index/history;it does not validate unstaged content or
ignored evidence. Record actual skips and affected checks at each checkpoint.

Visual Studio x64 C++ tools and Windows SDK are required for native builds:
  powershell -File client_patch/build.ps1
  powershell -File server/build_launcher.ps1

Exact-build patch/restore into a CLOSED working game copy:
  python -m client_patch.patcher.patch_client --game-dir "<game>" --dry-run
  python -m client_patch.patcher.patch_client --game-dir "<game>"
  python -m client_patch.patcher.patch_client --game-dir "<game>" --restore
Do not target the untouched recovery installation or a reserved manual candidate.
Source recipe23 covers GameAssembly.dll,UnityPlayer.dll and nested chrome_elf.dll/
libcef.dll. RUNTIME_VALIDATED remains false. Prerelease174 binds recipe23.
Use the guides/index for asset import,advanced verified setup and diagnostic tools.

DOCUMENTATION HISTORY
Long checkpoint logs and prior instructions are preserved byte-for-byte under
  docs/history/2026-10-24/
Focused evidence files keep their original paths for tools and retained reports.
The current roadmap is the work queue;historical pending/next labels are not.
