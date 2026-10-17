BATTLE ACES RESURRECTION - WINDOWS SERVER AND CLIENT ADAPTER

Development project for private Battle Aces build 37822 matches. Windows x64
server and clients are the current target. See docs/SERVER_REPLACEMENT_PLAN.txt
for the requested outcome and docs/STATUS.txt for evidence and remaining work.

The coordinator runs each original simulation in an isolated worker, validates
decks/actions and serves multiple private rooms. Twenty successive native matches
and worker crash containment are verified. Two client matches in the same processes
now pass; broader manual/failure flows, complete telemetry removal, private internet
hosting and release packaging remain under development.
Do not treat this development baseline as the finished release.

SOURCE LAYOUT
  server/                 Python server, protocol and native simulation adapter
  client_patch/src/       our C++ helper source
  client_patch/patcher/   exact-build patch recipes and reversible installer
  client_patch/launcher/  client config example, initializer and launcher
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

The installer verifies original component SHA256s, preserves originals locally under
.battleaces-resurrection/original/, and refuses unknown modifications. For an
existing compatible prototype patch, --original may identify a verified original
DLL. Do not target the untouched recovery installation.
Current guards modify GameAssembly.dll, UnityPlayer.dll and the bundled nested
chrome_elf.dll; the manifest records all three hashes. Reviewed telemetry guards
are included, but complete reporting
removal remains unverified. See docs/telemetry.txt for the exact scope.

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

COMMUNITY CLIENT CONFIGURATION
Create a personal editable config once:
  powershell -File client_patch/launcher/Initialize-ClientConfig.ps1 -GameDirectory "<game>"
Edit client_patch/launcher/client-config.json: set server_host to the server's IP
or DNS name and server_port to its TCP port (default 47623). Then launch with:
  powershell -File client_patch/launcher/Launch-Client.ps1
See docs/client-configuration.txt for room/player settings and current transport
limits. Personal configs are ignored by Git; the example is included in source.

Automated graphical two-client baseline (local diagnostics, normal game commands):
  powershell -File tools/Run-LocalMatch.ps1 -GameDirectory "<game>" -RunName unique-name -AutoReady -Smoke -DeckSmoke -SurrenderSmoke -DurationSeconds 100
  python -m server.verify_dedicated_run local/matches/unique-name --runtime-directory "<game>/investigation/runtime" --processes local/matches/unique-name/processes.json

Runtime environment overrides:
  BA_ASSET_DIR        locally supplied map/catalog/descriptors directory
  BA_SIMULATION_DLL   matching Windows x64 Simulation.dll
  BA_DATA_DIR         profiles, match history and local diagnostics

Default listener:127.0.0.1:47623, plaintext development mode with self-reported
identities. Plaintext non-loopback binds are rejected. The server's optional TLS
listener binds profiles to revocable credentials; see docs/admission.txt and
docs/tls-transport.txt. Real TLS tests reach a lobby, but graphical-client TLS and
public handshake admission limits remain pending. Internet play is not ready.

Original-game assets remain local. Release artifacts will contain our executable
helper and tooling, not the original or patched full game binaries.
