#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdio.h>
#include <vector>
#include "launch_args.hpp"
int wmain() {
    const std::vector<std::wstring> values={L"",L"simple",L"space path",L"a\tb",L"tail\\",
        L"tail space\\",L"\\\\",L"quote\"inside",L"\\\"quoted",L"a\\\\\"b\\",L"\u754c\u00e9\U0001F680",
        L"%PATH%",L"$(no-shell)",L"&|<>^",L"--config",L"C:\\ordinary folder\\host.json"};
    std::wstring command=L"python.exe";
    for(const auto& value:values)command+=L" "+ba_server_launcher::quote(value);
    int count=0;auto args=CommandLineToArgvW(command.c_str(),&count);
    bool okay=args && count==static_cast<int>(values.size()+1);
    if(okay)for(size_t i=0;i<values.size();++i)if(values[i]!=args[i+1])okay=false;
    if(args)LocalFree(args);
    if(!okay){fputs("Server launcher Unicode/quoting roundtrip failed.\n",stderr);return 1;}
    puts("Server launcher arguments match independent Windows argv decoding.");return 0;
}
