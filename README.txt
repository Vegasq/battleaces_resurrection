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

Server community control v1 adds a connected-player directory, targeted invites,
host-controlled custom starts and same-connection rematches. Scripted clients pass
two matches using the real simulation, with a third player kept outside both games.
The native Invite Friend/Start UI adapter and Try Deck vs AI are still unfinished.
The opt-in custom picker now renders the connected-player list and passes native
binding/pool-lifecycle tests; its invitation actions remain disabled. Details and
reproduction commands are in docs/community-client.txt.
See docs/community-protocol.txt and docs/community-lobby.txt for scope and evidence.

Current game wire protocol3 requires updating both helper and server. The server
selects a bounded input window with --input-window (2..12, default6); both players
receive the same setting. See docs/protocol-v3.txt and docs/network-qualification.txt
for compatibility,command-delay tradeoffs and measured network tests.

SOURCE LAYOUT
  server/                 Python server, protocol and native simulation adapter
  client_patch/src/       our C++ helper source
  client_patch/patcher/   exact-build patch recipes and reversible installer
  client_patch/launcher/  client config example, initializer and launcher
  client_patch/transport/ verified TLS/authentication parent for the secure client
  tools/                  local extraction/import and publication audit
  tests/                  synthetic tests requiring no game installation
  docs/                   implementation plan, protocol and knowledge base

No game binaries, maps, catalogs, descriptors or captured game fixtures are
distributed here. Supply a compatible game installation locally. Generated assets,
build output and test evidence belong under ignored local/, build/ or dist/.

SOURCE CHECKS (Python 3.12)
  python -m unittest discover -s tests -v
  python -m tools.audit_repository --history

Optional real-simulation custom lobby/rematch probe (Windows, locally imported assets):
  python -m tools.verify_community_native --assets "<asset directory>" --output local/community-native-test
This uses scripted TCP peers and deliberate test surrender, without graphical UI.

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

The commands above use schema1 for plaintext loopback development. The secure
launcher uses secure-client-config.example.json (schema2), an explicit trusted CA,
expected server name and a private invite handoff. The server IP/DNS and port are
editable in either config. See docs/secure-client-transport.txt for installation,
trust/enrollment, its test boundaries and the separate Launch-SecureClient.ps1.

Automated graphical two-client baseline (local diagnostics, normal game commands):
  powershell -File tools/Run-LocalMatch.ps1 -GameDirectory "<game>" -RunName unique-name -AutoReady -Smoke -DeckSmoke -SurrenderSmoke -DiagnosticAudit -DurationSeconds 100
  python -m server.verify_dedicated_run local/matches/unique-name --runtime-directory "<game>/investigation/runtime" --processes local/matches/unique-name/processes.json

Runtime environment overrides:
  BA_ASSET_DIR        locally supplied map/catalog/descriptors directory
  BA_SIMULATION_DLL   matching Windows x64 Simulation.dll
  BA_DATA_DIR         profiles, match history and local diagnostics

Default listener:127.0.0.1:47623, plaintext development mode with self-reported
identities. Plaintext non-loopback binds are rejected. The server's optional TLS
listener binds profiles to revocable credentials; see docs/admission.txt and
docs/tls-transport.txt. Raw TLS handshakes have global/source limits and real TLS
tests reach a lobby. Two actual clients completed two matching TLS1.3 matches in
the same processes with changed decks; see docs/secure-client-transport.txt.
Private-file enrollment, manual UI and cross-network qualification remain pending.
Internet play is not ready.

Original-game assets remain local. Release artifacts will contain our executable
helper and tooling, not the original or patched full game binaries.
