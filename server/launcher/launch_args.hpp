#pragma once
#include <string>

namespace ba_server_launcher {
// Quote one Microsoft CRT argv token. No command shell or expansion is involved.
inline std::wstring quote(const std::wstring& value) {
    std::wstring result=L"\"";size_t slashes=0;
    for(wchar_t ch:value) {
        if(ch==L'\\'){++slashes;continue;}
        result.append(ch==L'\"'?slashes*2+1:slashes,L'\\');slashes=0;
        result.push_back(ch);
    }
    result.append(slashes*2,L'\\');result.push_back(L'\"');return result;
}
}
