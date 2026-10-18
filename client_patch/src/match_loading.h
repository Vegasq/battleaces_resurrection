#pragma once
#include "match_loading_state.hpp"
namespace ba_match_loading {
static Ticket begin(Source,const std::string& identity,Stage);
static void advance(Ticket,Stage);
static void success(Ticket);
static void cancel(Ticket,const char* reason);
static void error(Ticket,const char* playerMessage);
static void dismissNotice(Ticket,const char* reason);
static void update(void* front);
}
namespace ba_match_loading_smoke { static void update(void* front); }
