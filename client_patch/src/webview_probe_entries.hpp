#pragma once
#include <cstdint>
namespace ba_webview_probe_entries {
struct Entry {uint32_t rva;const char* sha256;};
inline constexpr Entry entries[]={
    {0x54ad160,"83138ad6e0501eb9d5c79b6e78ab3e91b0064ccf3c15a99e7e49f49af751740d"}, // Vuplex.WebView.CanvasWebViewPrefab::Instantiate
    {0x54a6880,"dfdd206ebfa25c291ec829ea933024f98bfd20f0c0f1459269510f4783e7f47c"}, // Vuplex.WebView.BaseWebViewPrefab::WaitUntilInitialized
    {0x54a60b0,"5f9bddb2f6479cf385289036d868e6c9307091c8ad51908389154ba4c5ac9214"}, // Vuplex.WebView.BaseWebViewPrefab::get_WebView
    {0x54a64c0,"6ac615068d712128ca5c952571aa76ab747224cefa1a2c8dede8476e918e32d1"}, // Vuplex.WebView.BaseWebViewPrefab::Destroy
    {0x54c31c0,"5763d7c342a28804c6ea22a6b5e65ad86ff674b24c128b8ff802b0cd749d8e34"}, // Vuplex.WebView.StandaloneWebView::SetCachePath
    {0x54c4620,"0e29f367d9879fd8933a8912e2d287736b222844963d850938ea79c9b5c8448b"}, // Vuplex.WebView.StandaloneWebView::TerminateBrowserProcess
    {0x54c7730,"9119c4704fe854b86a017c66d610c89bceb86efd3276e22e8fa4540c6fc7dacc"}, // Vuplex.WebView.StandaloneWebView::WebView_browserProcessIsRunning
    {0x54c23d0,"bf95517839db4e61d14bf30c395b900e65770c2847f47ab60848d5cebcf256f8"}, // Vuplex.WebView.StandaloneWebView::LoadHtml
    {0x54cfdc0,"8dbfffff29eccbfddcceaf0f37afb86231f5dd9cb856b489a2f7fdffb242a41b"}, // Vuplex.WebView.Internal.BaseWebView::Dispose
    {0x54cf440,"a3cd087f7764c330e4230f8adaa12e2e3cdcfbba9bd978863fa2f6944a37df1d"}, // Vuplex.WebView.Internal.BaseWebView::get_IsInitialized
    {0x84abc0,"137eb7dc1e0d4a2eb5a8cb78d1ee65b58055ed85fce21b3afd45c6ac305bcad5"}, // Vuplex.WebView.Internal.BaseWebView::get_IsDisposed
    {0x845d80,"df35057d3527001ed9958fe9fee2802f75e87c1f48672e48ff11e1147d348293"}, // Vuplex.WebView.Internal.BaseWebView::get_Size
    {0x54d16f0,"28935736d3a0d25967ab2886ae70894f5e0bdd2ab293312991eb3e21fcf5013a"}, // Vuplex.WebView.Internal.BaseWebView::WaitForNextPageLoadToFinish
};
}
