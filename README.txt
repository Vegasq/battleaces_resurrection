BATTLE ACES RESURRECTION - WINDOWS SERVER AND CLIENT ADAPTER

Development project for private Battle Aces build 37822 matches. Windows x64
server and clients are the current target. See docs/SERVER_REPLACEMENT_PLAN.txt
for the requested outcome and docs/STATUS.txt for evidence and remaining work.

The baseline runs the original simulation in a standalone process, validates
decks/actions and sequences inputs for patched clients. Private internet hosting,
multiple rooms, rematches without a client restart, and telemetry removal are
under development. Do not treat this development baseline as the finished release.

SOURCE LAYOUT
  server/                 Python server, protocol and native simulation adapter
  client_patch/src/       our C++ helper source
  client_patch/patcher/   exact-build patch recipes and reversible installer
  client_patch/launcher/  development client launcher
  tools/                  local extraction/import and publication audit
  tests/                  synthetic tests requiring no game installation
  docs/                   implementation plan, protocol and knowledge base

No game binaries, maps, catalogs, descriptors or captured game fixtures are
distributed here. Supply a compatible game installation locally. Generated assets,
build output and test evidence belong under ignored local/, build/ or dist/.

SOURCE CHECKS (Python 3.12)
  python -m unittest discover -s tests -v
  python -m tools.audit_repository --history

The audit reads the Git index and reachable history, not ignored runtime files.
Review the staged diff as well; automated scans cannot establish provenance.

BUILD THE CLIENT HELPER (Visual Studio x64 C++ tools and Windows SDK required)
  powershell -File client_patch/build.ps1

INSTALL INTO A WORKING GAME COPY (close that game's processes first)
  python -m client_patch.patcher.patch_client --game-dir "<game directory>" --dry-run
  python -m client_patch.patcher.patch_client --game-dir "<game directory>"

The installer verifies the original SHA256, preserves the original locally under
.battleaces-resurrection/original/, and refuses unknown modifications. For an
existing compatible prototype patch, --original may identify a verified original
DLL. Do not target the untouched recovery installation.

RESTORE
  python -m client_patch.patcher.patch_client --game-dir "<game directory>" --restore

SERVER RUNTIME INPUTS
Default asset directory: local/assets/build-37822
Required local files: map-1v1.pb.gz, unit-catalog.json, descriptors/*.proto.json,
and Simulation.dll. After patching a working game copy, launch it with
-export-server-assets and wait for server-assets/export.json with complete=true,
then close it. Use normal graphics for the tested export path. This mode builds
local assets without joining a match. Import them with:
  python -m tools.import_assets --game-dir "<game>" --export-dir "<game>/server-assets" --original "<game>/.battleaces-resurrection/original/GameAssembly.dll"

The destination must be empty; use --destination under local/ for another bundle.
Import checks export hashes and regenerates the protobuf descriptors from the
original DLL and metadata. It copies the local simulation DLL and writes the
asset-manifest.json completion record. No asset download is involved.

Development commands can explicitly select existing local inputs:
  python -m server.dedicated_server --assets "<asset directory>" --dll "<Simulation.dll>"
  powershell -File client_patch/launcher/Launch-Client.ps1 -GameDirectory "<game>" -Slot 0

Automated graphical two-client baseline (local diagnostics, normal game commands):
  powershell -File tools/Run-LocalMatch.ps1 -GameDirectory "<game>" -RunName unique-name -AutoReady -Smoke -DeckSmoke -SurrenderSmoke -DurationSeconds 100
  python -m server.verify_dedicated_run local/matches/unique-name --runtime-directory "<game>/investigation/runtime" --processes local/matches/unique-name/processes.json

Runtime environment overrides:
  BA_ASSET_DIR        locally supplied map/catalog/descriptors directory
  BA_SIMULATION_DLL   matching Windows x64 Simulation.dll
  BA_DATA_DIR         profiles, match history and local diagnostics

Default listener: 127.0.0.1:47623. Protocol v2 currently supports one two-player
room with self-reported identities and no TLS. Keep this baseline on loopback or
a trusted private network while the internet-hosting milestone is implemented.

Original-game assets remain local. Release artifacts will contain our executable
helper and tooling, not the original or patched full game binaries.
