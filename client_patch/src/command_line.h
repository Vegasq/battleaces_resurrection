#pragma once
#include <string>
#include <vector>
#include <cwchar>

// Windows argument quoting, without shell execution or an extra DLL import.
// The executable token is retained and skipped by option lookups. Quotes can
// surround an entire token or just its value, e.g. -player-name="Player One".
namespace ba_command_line {
inline bool space(wchar_t c){return c==L' ' || c==L'\t';}
inline std::vector<std::wstring> parse(const wchar_t* command) {
    std::vector<std::wstring> result;
    const wchar_t* p=command;
    while(*p) {
        while(space(*p))++p;
        if(!*p)break;
        std::wstring value;bool quoted=false;
        while(*p && (quoted || !space(*p))) {
            size_t slashes=0;while(*p==L'\\'){++slashes;++p;}
            if(*p==L'"') {
                value.append(slashes/2,L'\\');
                if(slashes%2){value.push_back(L'"');++p;}
                else if(quoted && p[1]==L'"'){value.push_back(L'"');p+=2;}
                else {quoted=!quoted;++p;}
            } else {
                value.append(slashes,L'\\');
                if(!*p || (!quoted && space(*p)))break;
                value.push_back(*p++);
            }
        }
        result.push_back(std::move(value));
    }
    return result;
}
inline bool value(const std::vector<std::wstring>& args,const wchar_t* key,std::wstring& out) {
    const size_t length=wcslen(key);
    for(size_t index=1;index<args.size();++index) {
        if(args[index].compare(0,length,key)==0){out=args[index].substr(length);return true;}
    }
    return false;
}
inline bool has(const std::vector<std::wstring>& args,const wchar_t* flag) {
    for(size_t index=1;index<args.size();++index)if(args[index]==flag)return true;
    return false;
}
}
