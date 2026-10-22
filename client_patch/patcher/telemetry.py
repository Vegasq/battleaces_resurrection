"""Exact-build telemetry patch transformations; no file or process operations.

These 111 recipes have static source/control-flow review. The complete recipe
set has not been runtime validated; recipe2's 59 had a bounded compatibility run.
They do not establish complete telemetry removal; see docs/telemetry.txt.
Only brief patch safety signatures are included, never original game payloads.
"""
from dataclasses import dataclass
import hashlib
from types import MappingProxyType

GAME_BUILD = 37822
RECIPE_VERSION = 17
RUNTIME_VALIDATED = False
VALIDATION_STATUS = "Scoped native compatibility verified; full lifecycle/report-removal qualification pending"
UNRESOLVED_COMPONENTS = (
    "Native Unity indirect callback consumers and independent reporter entry points",
    "Native identity and archive activation runtime/lifecycle qualification",
    "Internal hardware collection/constructor paths and indirect configuration callers",
    "Deferred/cached delivery and error-path process/network qualification",
    "CEF descendant initialization and analytics in remote web content",
)
CEF_COMPONENT_PATH = (
    "Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/chrome_elf.dll"
)
CEF_HANDLER_COMPONENT_PATH = (
    "Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/libcef.dll"
)


@dataclass(frozen=True)
class Patch:
    label: str
    rva: int
    offset: int
    guard: bytes
    replacement: bytes


@dataclass(frozen=True)
class Component:
    original_sha256: str
    patches: tuple[Patch, ...]


# Signatures include the surrounding original instructions for exact-build checks.
# All guards are validated against the immutable input before any replacement.
COMPONENTS = MappingProxyType({
    'GameAssembly.dll': Component(
        'e59d08c01479b27404778048d7e13546dbf3771f6b3912744c7c2bdf80c4e758',
        (
            Patch('Uncapped.BugsnagCrashReporter::Subs', 0x3cc2140, 0x3cc0740,
                  bytes.fromhex('40534883ec50803d22731903000f859f'), bytes.fromhex('c3')),
            Patch('Uncapped.BugsnagCrashReporter::OnApplicationQuit', 0x3cc2af0, 0x3cc10f0,
                  bytes.fromhex('40534883ec20803d7369190300754b48'), bytes.fromhex('c3')),
            Patch('Uncapped.BugsnagCrashReporter::AddStaticMetadata', 0x3cc2bc0, 0x3cc11c0,
                  bytes.fromhex('48895c2408574883ec30803da0681903'), bytes.fromhex('c3')),
            Patch('Uncapped.BugsnagCrashReporter::RegisterDynamicMetadataEnricher', 0x3cc2c90, 0x3cc1290,
                  bytes.fromhex('48895c24104889742418574883ec3080'), bytes.fromhex('31c0c3')),
            Patch('Uncapped.BugsnagCrashReporter::LeaveBreadcrumb', 0x3cc2ea0, 0x3cc14a0,
                  bytes.fromhex('48895c24084889742410574883ec3080'), bytes.fromhex('c3')),
            Patch('Uncapped.BugsnagCrashReporter::SendReport', 0x3cc2ff0, 0x3cc15f0,
                  bytes.fromhex('48895c2408574883ec30803d73641903'), bytes.fromhex('c3')),
            Patch('Uncapped.BugsnagCrashReporter::UnregisterDynamicMetadataEnricher', 0x3cc3150, 0x3cc1750,
                  bytes.fromhex('48895c2418574883ec60803d15631903'), bytes.fromhex('c3')),
            Patch('Uncapped.AnalyticsUIActions::AddPlayerPing', 0x3e2f2f0, 0x3e2d8f0,
                  bytes.fromhex('48895c240848896c2410488974241848'), bytes.fromhex('c3')),
            Patch('Uncapped.AnalyticsUIActions::AddPlayerSpray', 0x3e2f4e0, 0x3e2dae0,
                  bytes.fromhex('48895c240848896c2410488974241848'), bytes.fromhex('c3')),
            Patch('Uncapped.AnalyticsUIActions::AddPlayerEmote', 0x3e2f6d0, 0x3e2dcd0,
                  bytes.fromhex('48895c240848896c2410488974241848'), bytes.fromhex('c3')),
            Patch('Uncapped.AnalyticsUIActions::AddPlayerIntelligenceBarAction', 0x3e2f8c0, 0x3e2dec0,
                  bytes.fromhex('48895c24084889742410574883ec4080'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBISampleClientTelemetry', 0x3e320c0, 0x3e306c0,
                  bytes.fromhex('48895c24084889742410574883ec2080'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientWalletTelemetry', 0x3e32250, 0x3e30850,
                  bytes.fromhex('48895c241048896c2418488974242057'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientWalletTelemetry', 0x3e324a0, 0x3e30aa0,
                  bytes.fromhex('48895c2410488974241848897c242048'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientFTUEEventTelemetry', 0x3e32a10, 0x3e31010,
                  bytes.fromhex('48895c240848896c2410488974241857'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::DispatchBIClientTelemetryFromReward', 0x3e32bb0, 0x3e311b0,
                  bytes.fromhex('48895c24104889742418574154415748'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientWalletBalanceTelemetry', 0x3e32d00, 0x3e31300,
                  bytes.fromhex('48895c240848896c2410488974241848'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientErrorEventTelemetry', 0x3e32f30, 0x3e31530,
                  bytes.fromhex('48895c240848896c2410488974241857'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientShopErrorEventTelemetry', 0x3e330d0, 0x3e316d0,
                  bytes.fromhex('48895c240848896c2410488974241848'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientOptionToggleTelemetry', 0x3e33320, 0x3e31920,
                  bytes.fromhex('48895c240848896c2410488974241857'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientCosmeticsModifiedTelemetry', 0x3e33540, 0x3e31b40,
                  bytes.fromhex('48895c2410488974241848894c240857'), bytes.fromhex('c3')),
            Patch('Uncapped.FrontServerIntegration::SendBIClientDeckModifiedTelemetry', 0x3e33a90, 0x3e32090,
                  bytes.fromhex('488bc448895810488970184889480857'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Bugsnag::Start', 0x810660, 0x80ec60,
                  bytes.fromhex('48895c2408574883ec20803d8d846306'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Bugsnag::Start', 0x8106f0, 0x80ecf0,
                  bytes.fromhex('48895c2408574883ec40488bd9803dfb'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Bugsnag::Notify', 0x810ce0, 0x80f2e0,
                  bytes.fromhex('48895c240848896c2410488974241857'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Bugsnag::Notify', 0x810dc0, 0x80f3c0,
                  bytes.fromhex('48895c24084889742410574883ec3080'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Bugsnag::Notify', 0x810e90, 0x80f490,
                  bytes.fromhex('48895c24084889742410574883ec3080'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Bugsnag::Notify', 0x810f60, 0x80f560,
                  bytes.fromhex('48896c241856415641574883ec30803d'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Client::Send', 0x8147e0, 0x812de0,
                  bytes.fromhex('48895c2408574883ec20488bfa488bd9'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Client::NotifyFromUnityLog', 0x814880, 0x812e80,
                  bytes.fromhex('48895c241855415641574883ec70803d'), bytes.fromhex('c3')),
            Patch('.<DeliverCachedPayloads>d__36::MoveNext', 0x8201f0, 0x81e7f0,
                  bytes.fromhex('4889742410574883ec20803d79896206'), bytes.fromhex('31c0c3')),
            Patch('.<ProcessCachedItems>d__37::MoveNext', 0x8204c0, 0x81eac0,
                  bytes.fromhex('48894c2408535657415641574881eca0'), bytes.fromhex('31c0c3')),
            Patch('.<PushToServer>d__21::MoveNext', 0x820de0, 0x81f3e0,
                  bytes.fromhex('48895c241048894c2408565741544156'), bytes.fromhex('31c0c3')),
            Patch('BugsnagUnity.Delivery::Deliver', 0x81c6a0, 0x81aca0,
                  bytes.fromhex('488954241048894c2408535657415441'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.Delivery::StartDeliveringCachedPayloads', 0x81f730, 0x81dd30,
                  bytes.fromhex('48895c2408574883ec30488bd9803d2f'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.PayloadManager::AddPendingPayload', 0x824450, 0x822a50,
                  bytes.fromhex('48895c24084889742410574156415748'), bytes.fromhex('31c0c3')),
            Patch('BugsnagUnity.CacheManager::SaveDeviceIdToCache', 0x836ad0, 0x8350d0,
                  bytes.fromhex('48895c2408574883ec20803d47216106'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.CacheManager::SaveSessionToCache', 0x836f10, 0x835510,
                  bytes.fromhex('48895c24084889742410574883ec3080'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.CacheManager::SaveEventToCache', 0x837020, 0x835620,
                  bytes.fromhex('48895c24084889742410574883ec3080'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.CacheManager::WritePayloadToDisk', 0x837130, 0x835730,
                  bytes.fromhex('498bc04533c94c8bc2488bd0e9ff0500'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.CacheManager::WriteFile', 0x837740, 0x835d40,
                  bytes.fromhex('48895c2408574883ec40498bf8488bc2'), bytes.fromhex('c3')),
            Patch('BugsnagUnity.BugsnagAutoInit::OnBeforeSceneLoadRuntimeMethod', 0x80b370, 0x809970,
                  bytes.fromhex('40534883ec20803d52d7630600756d48'), bytes.fromhex('c3')),
            # Keep original pending lookup/removal and all saved-register exits.
            # Entry RET would strand existing pending owners;WriteFile RET alone
            # still allows inline enumeration/eviction after the attempted write.
            Patch('Bugsnag failure session bypass retains pending cleanup', 0x824bf1, 0x8231f1,
                  bytes.fromhex('488b7b10488b68184c8b70104885ff0f'), bytes.fromhex('e9ef00000090909090909090')),
            Patch('Bugsnag failure event bypass retains pending cleanup', 0x824d3a, 0x82333a,
                  bytes.fromhex('488b7b10488b68184c8b70104885ff0f'), bytes.fromhex('e9a6ffffff90909090909090')),
            Patch('Bugsnag CacheSession bypass retains pending cleanup', 0x824e50, 0x823450,
                  bytes.fromhex('488b7b10488b68184c8b70104885ff0f'), bytes.fromhex('e9e700000090909090909090')),
            Patch('Bugsnag CacheEvent bypass retains pending cleanup', 0x824fa0, 0x8235a0,
                  bytes.fromhex('488b7b10488b68184c8b70104885ff0f'), bytes.fromhex('e9e700000090909090909090')),
            # Select the existing String.Empty path after configuration/type init.
            # Keep its null-config exception and all prologue/epilogue ownership.
            Patch('Bugsnag cached device identity uses existing disabled branch', 0x83692d, 0x834f2d,
                  bytes.fromhex('0f8475010000488b05be57310683b8e0'), bytes.fromhex('e97601000090')),
        ),
    ),
    'UnityPlayer.dll': Component(
        'ac144d56d53f07904d52ed27a1539de90bc3290038fe52d73d2f6b268c85d6bc',
        (
            Patch('force native crash/error reporting initialization disabled', 0xc90c2a, 0xc9002a,
                  bytes.fromhex('0fb64210488bf2884101488bd984c00f'), bytes.fromhex('31c09090')),
            Patch('prevent Unity crash-handler child creation', 0x80366f, 0x802a6f,
                  bytes.fromhex('0f85a40500004c39b424200800000f84'), bytes.fromhex('e9a505000090')),
            Patch('native in-process report uploader defense', 0xc93d10, 0xc93110,
                  bytes.fromhex('488bc44889480855488da868ffffff48'), bytes.fromhex('c3')),
            # Reject only state1 preparation through the existing false-return
            # tail,including its reentrancy reset. Other transitions/cleanup stay.
            Patch('Unity analytics initialization transition declines before preparation', 0xc3bafc, 0xc3aefc,
                  bytes.fromhex('488b03488bcbff908000000041b001c6'), bytes.fromhex('e90a00000090909090909090909090')),
            # The separate configuration route also dispatches preparation.
            # Its caller forwards AL after releasing its own temporary strings.
            Patch('Unity analytics configuration preparation declines before borrowed input', 0xc34270, 0xc33670,
                  bytes.fromhex('48895c240848896c2410488974241857'), bytes.fromhex('31c0c3')),
            # Always take the original retained-SSO fast return. Do not acquire,
            # migrate or persist a cloud ID;do not return null/fabricate an owner.
            Patch('Unity cloud user ID getter retains value without acquisition', 0xc478f5, 0xc46cf5,
                  bytes.fromhex('7410488d41484881c4c0010000415f5b'), bytes.fromhex('9090')),
            # Keep initialized performance storage; its getters are not null-safe.
            # The existing exit and destructor both handle registered=false.
            Patch('skip performance callbacks after object initialization', 0xd84ec6, 0xd842c6,
                  bytes.fromhex('0f857d0100004c8bcbc603014c8d0587'), bytes.fromhex('e97e01000090')),
            Patch('performance default disabled', 0xd84e3e, 0xd8423e,
                  bytes.fromhex('c740080001000048897810c6401901e8'), bytes.fromhex('c7400800000000')),
            Patch('performance setter remains disabled', 0x292110, 0x291510,
                  bytes.fromhex('84c9488b0d8fcba7010f95c24883c108'), bytes.fromhex('31c9')),
            # Preserve main/interface/session allocations. Do not RET c8c510:
            # public getters and performance notifications require these objects.
            Patch('skip session callbacks after object initialization', 0xc8c5f3, 0xc8b9f3,
                  bytes.fromhex('0f85b80000004c8bcbc64308014c8d'), bytes.fromhex('e9b900000090')),
            Patch('suppress main analytics Start registration', 0xc66c20, 0xc66020,
                  bytes.fromhex('40574883ec7080b9c015000000488b'), bytes.fromhex('c3')),
            Patch('suppress base analytics Start registration', 0xc2f570, 0xc2e970,
                  bytes.fromhex('40534883ec2080b9c015000000488b'), bytes.fromhex('c3')),
            Patch('analytics default disabled', 0xc333da, 0xc327da,
                  bytes.fromhex('41c6865116000001e8c93f03004c89'), bytes.fromhex('41c6865116000000')),
            # XOR forces the following SETNE false while retaining its notifier.
            Patch('analytics setter remains disabled', 0x2078b0, 0x206cb0,
                  bytes.fromhex('84c9488b0d6f72b0010f95c0388151'), bytes.fromhex('31c9')),
            Patch('device statistics default disabled', 0xc2f3fc, 0xc2e7fc,
                  bytes.fromhex('c687c315000001e878340000488bc7'), bytes.fromhex('c687c315000000')),
            Patch('device statistics setter remains disabled', 0x207a60, 0x206e60,
                  bytes.fromhex('84c9488b0dbf70b0010f95c03881c3'), bytes.fromhex('31c9')),
            # Before worker initialization, common submission bypasses the
            # enabled-reporter check. Both event routes therefore have guards.
            Patch('common native event submission returns false', 0xc381d0, 0xc375d0,
                  bytes.fromhex('44894c24204c894424184889542410'), bytes.fromhex('31c0c3')),
            Patch('limited native event submission returns disabled status', 0xc37400, 0xc36800,
                  bytes.fromhex('48895c2408488974241848897c2420'), bytes.fromhex('b802000000c3')),
            Patch('native reporter gate returns false before collector registration', 0xc33440, 0xc32840,
                  bytes.fromhex('4883ec288b81c815000085c0488b15'), bytes.fromhex('31c0c3')),
            # These explicit APIs bypass the disabled Start/enabled gates and
            # use separate configuration storage at main+1470. Return their
            # existing false result before argument conversion/device collection.
            # Registration fd42d0 pairs each name/function in the same iteration;
            # both native bodies return boolean AL (no output buffer/ownership).
            Patch('RemoteConfigSettings QueueConfig returns false before serialization', 0x1fd3a0, 0x1fc7a0,
                  bytes.fromhex('4055535657415441554157488d6c24f0'), bytes.fromhex('31c0c3')),
            Patch('RemoteConfigSettings SendDeviceInfo returns false before collection', 0x1fda50, 0x1fce50,
                  bytes.fromhex('40534881ec50060000488b1dc810b101'), bytes.fromhex('31c0c3')),
            # The shared append also has an internal c300f0 caller BEFORE its
            # initialized-state check. These boolean sinks own only local
            # temporaries;entry false preserves caller-owned payload cleanup.
            # Retain the drain/lifecycle and all generic serialization helpers.
            Patch('native configuration event append returns false before collection', 0xc392c0, 0xc386c0,
                  bytes.fromhex('48895c24205556574154415541564157'), bytes.fromhex('31c0c3')),
            Patch('native configuration payload append returns false before serialization', 0xc2e240, 0xc2d640,
                  bytes.fromhex('405356574883ec60488bfac744245449'), bytes.fromhex('31c0c3')),
            # Preserve the original pending-device marker 2->0, then return
            # before constructing the local OS/interface/device payload. Main,
            # its independently initialized cache/settings and caller cleanup
            # remain valid. Never RET the payload constructor or shared helpers.
            Patch('native device payload preserves queue progress without collection', 0xc40840, 0xc3fc40,
                  bytes.fromhex('885424105553564154488dac2448f8ffff4881ecb80800004c8be1b00133c989'),
                  bytes.fromhex('83b99014000002750ac7819014000000000000c3')),
            # Same-index original icall registration binds QueueEvent here.
            # Its four managed inputs are borrowed; all native ownership and
            # cleanup are local. False precedes both name conversion and the
            # c38c80 managed-payload adapter, not just the guarded final sink.
            Patch('Analytics QueueEvent returns false before managed payload conversion', 0x20c560, 0x20b960,
                  bytes.fromhex('4055535657415441554157488d6c24f0'), bytes.fromhex('31c0c3')),
            # Caller owns already constructed builder/output objects and accepts
            # their empty defaults. Retain the original dirty-config tail, all
            # caller cleanup and drain marker progress;do not RET the drain or
            # the serializer that consumes a locally copied string.
            Patch('skip analytics configuration identity preparation preserving dirty tail', 0xc2f790, 0xc2eb90,
                  bytes.fromhex('48895c24204c89442418488954241055'), bytes.fromhex('e95b090000')),
            # A separate state-one path performs the same shared platform query.
            # Select its existing unknown sentinel without changing construction,
            # destruction or state transition. Never patch shared query9fb910.
            Patch('analytics state preparation uses existing unknown device sentinel', 0xc2fc09, 0xc2f009,
                  bytes.fromhex('e802bddcffeb07488d059193d50049c7'), bytes.fromhex('e902000000')),
            # Paired redirects:keep dirty reset,r13=0,state/be/drain processing
            # and ALL six nonvolatile saves/restores,including chained unwind
            # metadata. Skip BOTH local construction and matching destruction.
            Patch('skip ads identity payload construction retaining dirty state progress', 0xc3016b, 0xc2f56b,
                  bytes.fromhex('4c8d3d66a9df00c744246c490000004c'), bytes.fromhex('e9b3000000')),
            Patch('skip unconstructed ads identity cleanup after all unwind register saves', 0xc30273, 0xc2f673,
                  bytes.fromhex('4438adc80000000f857a020000488bb5'), bytes.fromhex('e904050000')),
            # Base virtual+d0 has the same initialized caller outputs as the
            # derived prep,but no dirty tail. Return before timestamp/string
            # acquisition;never RET the shared consuming serializer c4df10.
            Patch('skip base analytics configuration serialization before local acquisition', 0xc3a5d0, 0xc399d0,
                  bytes.fromhex('48895c240848896c2410488974241848'), bytes.fromhex('c3')),
            # Caller-owned output strings are already valid empty defaults.
            # Omit ONLY serialization;keep cache assignment,dirty flag,request
            # state/completion,locks and all original cleanup/unwind saves.
            Patch('skip state-three analytics cache serialization call', 0xc39d14, 0xc39114,
                  bytes.fromhex('e827440100488d8fb8040000ff150a07'), bytes.fromhex('9090909090')),
            Patch('skip session-tag analytics cache serialization call', 0xc3a2a5, 0xc396a5,
                  bytes.fromhex('e8963e0100488d8bb8040000ff157901'), bytes.fromhex('9090909090')),
            Patch('skip identity-change analytics cache serialization call', 0xc41f0c, 0xc4130c,
                  bytes.fromhex('e82fc20000488d8bb8040000ff151285'), bytes.fromhex('9090909090')),
            # virtual+40 performs a separate query BEFORE the last serialization
            # call above. Select its existing unknown fallback;retain AL=1 and
            # string ownership. No shared query or whole state function RET.
            Patch('analytics identity refresh uses existing unknown device sentinel', 0xc32468, 0xc31868,
                  bytes.fromhex('e8a394dcffeb07488d05326bd50049c7'), bytes.fromhex('e902000000')),
            # Analytics-only synchronous void setters borrow managed strings.
            # Return before rooting/conversion/retained identity assignment.
            # Keep privacy controls,RemoteConfig tags and shared string helpers.
            Patch('Unity Analytics custom user identity setter before input conversion', 0x2048a0, 0x203ca0,
                  bytes.fromhex('4055534157488d6c24b94881ec900000'), bytes.fromhex('c3')),
            Patch('Unity Analytics custom device identity setter before input conversion', 0x204cb0, 0x2040b0,
                  bytes.fromhex('4055534157488d6c24b94881ec900000'), bytes.fromhex('c3')),
            # Keep borrowed-input validation,tracking/dirty updates,state read,
            # conditional drain and all unwind/cleanup. Omit only retained ID
            # assignment,matching the original self-assignment skip path.
            Patch('skip native ads callback retained identity copy preserving progress', 0xc30838, 0xc2fc38,
                  bytes.fromhex('e843ae52ff4088bb8801000033c0c683'), bytes.fromhex('9090909090')),
            # Return the original analytics-disabled result before borrowing/
            # converting event inputs or acquiring local owners. Scalar EAX,
            # no caller-owned output or queued completion is abandoned.
            Patch('Unity Analytics SendCustomEventName before input conversion', 0x208350, 0x207750,
                  bytes.fromhex('40555341544157488dac24a8feffff48'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics SendCustomEvent before wrapper access', 0x208840, 0x207c40,
                  bytes.fromhex('4883ec284c8bc1488d54243033c9ff15'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics SendEventWithLimit before input conversion', 0x20afa0, 0x20a3a0,
                  bytes.fromhex('4055535657415441554157488d6c24e0'), bytes.fromhex('b802000000c3')),
            # Remaining reviewed event controls/registration/transaction entries
            # use the same scalar disabled status,never Boolean false.
            Patch('Unity Analytics Transaction before input conversion', 0x207ad0, 0x206ed0,
                  bytes.fromhex('488bc4554155488da8d8feffff4881ec'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics IsCustomEventWithLimitEnabled before input conversion', 0x208890, 0x207c90,
                  bytes.fromhex('40555741544157488d6c24c14881ec98'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics EnableCustomEventWithLimit before input conversion', 0x208c50, 0x208050,
                  bytes.fromhex('4055535741544157488d6c24c94881ec'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics IsEventWithLimitEnabled before input conversion', 0x209000, 0x208400,
                  bytes.fromhex('40555357415441554157488d6c24e848'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics EnableEventWithLimit before input conversion', 0x2096c0, 0x208ac0,
                  bytes.fromhex('4055535657415441554157488d6c24f0'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics RegisterEventWithLimit before input conversion', 0x209d80, 0x209180,
                  bytes.fromhex('488bc4554154488da8d8feffff4881ec'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics RegisterEventsWithLimit before input conversion', 0x20a610, 0x209a10,
                  bytes.fromhex('488bc44c894820554155488da8c8feff'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics SetEventWithLimitEndPoint before input conversion', 0x20b690, 0x20aa90,
                  bytes.fromhex('488bc4554157488da848ffffff4881ec'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics SetEventWithLimitPriority before input conversion', 0x20bea0, 0x20b2a0,
                  bytes.fromhex('4055535657415441554157488d6c24f0'), bytes.fromhex('b802000000c3')),
            # Keep real Create/Destroy ownership;discard only the incoming name
            # before its first use,selecting the original empty-name path.
            Patch('Unity Analytics CustomEventData Create ignores borrowed event name', 0x205084, 0x204484,
                  bytes.fromhex('488bfac7451b01000000488bd9c645f7'), bytes.fromhex('31ff90')),
            Patch('Unity Analytics CustomEventData AddString before borrowed input access', 0x205550, 0x204950,
                  bytes.fromhex('40555356574157488d6c24c04881ec40'), bytes.fromhex('31c0c3')),
            Patch('Unity Analytics CustomEventData AddInt32 before borrowed input access', 0x205cd0, 0x2050d0,
                  bytes.fromhex('44894424185553574157488d6c24c148'), bytes.fromhex('31c0c3')),
            Patch('Unity Analytics CustomEventData AddUInt32 before borrowed input access', 0x206110, 0x205510,
                  bytes.fromhex('44894424185553574157488d6c24c148'), bytes.fromhex('31c0c3')),
            Patch('Unity Analytics CustomEventData AddInt64 before borrowed input access', 0x206550, 0x205950,
                  bytes.fromhex('4c894424185553574157488d6c24c148'), bytes.fromhex('31c0c3')),
            Patch('Unity Analytics CustomEventData AddUInt64 before borrowed input access', 0x206a30, 0x205e30,
                  bytes.fromhex('4c894424185553574157488d6c24c148'), bytes.fromhex('31c0c3')),
            Patch('Unity Analytics CustomEventData AddBool before borrowed input access', 0x206f10, 0x206310,
                  bytes.fromhex('40555356574157488d6c24c94881ecd0'), bytes.fromhex('31c0c3')),
            Patch('Unity Analytics CustomEventData AddDouble before borrowed input access', 0x207340, 0x206740,
                  bytes.fromhex('f20f115424185553574157488d6c24c1'), bytes.fromhex('31c0c3')),
            # Continuous-event entries have synchronous disabled status2
            # before any collector factory/delegate ownership or completion.
            Patch('Unity Analytics ContinuousEvent InternalRegisterCollector before input work', 0x202050, 0x201450,
                  bytes.fromhex('40555357415441554157488d6c24d848'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics ContinuousEvent InternalSetEventHistogramThresholds before input work', 0x2026f0, 0x201af0,
                  bytes.fromhex('4055535657415441554157488dac2460'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics ContinuousEvent InternalSetCustomEventHistogramThresholds before input work', 0x203050, 0x202450,
                  bytes.fromhex('4055535657415441554157488d6c24f0'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics ContinuousEvent InternalConfigureCustomEvent before input work', 0x203710, 0x202b10,
                  bytes.fromhex('488bc45553415441554157488d688848'), bytes.fromhex('b802000000c3')),
            Patch('Unity Analytics ContinuousEvent InternalConfigureEvent before input work', 0x203df0, 0x2031f0,
                  bytes.fromhex('488bc45553415441554157488da818ff'), bytes.fromhex('b802000000c3')),
        ),
    ),
    CEF_COMPONENT_PATH: Component(
        '080e409112b33a0e4cc763cba6d3c206fd640dd9006cb60f2f05ab7e73279563',
        (
            # Normal absent-config branch preserves a disabled reporter object
            # and returns before Crashpad bootstrap/database initialization.
            Patch('CEF crash reporter config returns false before startup', 0x323a0, 0x317a0,
                  bytes.fromhex('4157415641554154565755534881ecf8'), bytes.fromhex('31c0c3')),
        ),
    ),
    CEF_HANDLER_COMPONENT_PATH: Component(
        '168352bebcc14245493791362b5bc7a5669b331933a74217a8a6c0967c85e44e',
        (
            # Explicit --type=crashpad-handler dispatch is independent of the
            # chrome_elf config loader. Zero propagates through caller-owned
            # cleanup and exits the child; -1 would start the browser path.
            Patch('CEF Crashpad handler exits cleanly before initialization', 0x17403d0, 0x173f9d0,
                  bytes.fromhex('4157415641554154565755534881ec28'), bytes.fromhex('31c0c3')),
        ),
    ),
})


def _apply_recipe(original: bytes, component: Component) -> bytes:
    """Validate one complete recipe, then return an equal-length patched copy."""
    if not isinstance(original, bytes):
        raise TypeError("original must be immutable bytes")
    if hashlib.sha256(original).hexdigest() != component.original_sha256:
        raise ValueError("Original build SHA256 does not match")

    for patch in component.patches:
        if (type(patch.offset) is not int or patch.offset < 0
                or not isinstance(patch.guard, bytes)
                or not isinstance(patch.replacement, bytes)
                or not patch.guard or not patch.replacement
                or len(patch.guard) > 32
                or len(patch.replacement) > len(patch.guard)):
            raise ValueError(f"Invalid patch recipe: {patch.label}")

    ordered = sorted(component.patches, key=lambda patch: patch.offset)
    previous_end = 0
    for patch in ordered:
        guard_end = patch.offset + len(patch.guard)
        if guard_end > len(original):
            raise ValueError(f"Patch guard outside original: {patch.label}")
        if patch.offset < previous_end:
            raise ValueError(f"Overlapping patch guards: {patch.label}")
        if original[patch.offset:guard_end] != patch.guard:
            raise ValueError(f"Original bytes mismatch: {patch.label}")
        previous_end = guard_end

    patched = bytearray(original)
    for patch in ordered:
        patched[patch.offset:patch.offset + len(patch.replacement)] = patch.replacement
    return bytes(patched)


def patch_component(name: str, original: bytes) -> bytes:
    """Patch a supported pristine component; reject unknown or modified input.

    ``name`` is an exact allow-listed game-relative path from COMPONENTS:
    GameAssembly.dll, UnityPlayer.dll, CEF_COMPONENT_PATH, or
    CEF_HANDLER_COMPONENT_PATH. There is no path
    normalization, basename fallback or file lookup; aliases are rejected.
    This function performs no I/O, never mutates its input, preserves file size
    and all bytes outside the recipe replacements, and does not update the PE
    checksum. An integrating installer must recompute its final checksum after
    composing other approved changes and provide atomic backup/rollback.
    Already-patched input is intentionally rejected rather than patched twice.
    """
    if not isinstance(name, str) or name not in COMPONENTS:
        raise ValueError("Unsupported telemetry component")
    return _apply_recipe(original, COMPONENTS[name])
