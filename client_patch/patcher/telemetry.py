"""Exact-build telemetry patch transformations; no file or process operations.

These 45 recipes have static source/control-flow review, not runtime validation.
They do not establish complete telemetry removal; see docs/telemetry.txt.
Only brief patch safety signatures are included, never original game payloads.
"""
from dataclasses import dataclass
import hashlib
from types import MappingProxyType

GAME_BUILD = 37822
RECIPE_VERSION = 1
RUNTIME_VALIDATED = False
VALIDATION_STATUS = "Static review and original-byte validation only"
UNRESOLVED_COMPONENTS = (
    "Native Unity analytics lifecycle",
    "Native Unity performance collection and delivery",
    "CEF/crashpad and analytics in remote web content",
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

    ``name`` is exactly GameAssembly.dll or UnityPlayer.dll, not a file path.
    This function performs no I/O, never mutates its input, preserves file size
    and all bytes outside the recipe replacements, and does not update the PE
    checksum. An integrating installer must recompute its final checksum after
    composing other approved changes and provide atomic backup/rollback.
    Already-patched input is intentionally rejected rather than patched twice.
    """
    if not isinstance(name, str) or name not in COMPONENTS:
        raise ValueError("Unsupported telemetry component")
    return _apply_recipe(original, COMPONENTS[name])
