#pragma once
#include <string>
namespace ba_remote_profiles {
static void freeze(void* front,void* config,const std::string& match,int mode);
static void update(void* front);
static bool resultReady(const std::string& match);
static void retire(const std::string& match);
}
