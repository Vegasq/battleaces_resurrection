#include "match_loading_state.hpp"
#include <cassert>
#include <iostream>
using namespace ba_match_loading;
int main() {
    Model model;
    const auto first=model.begin(Source::Custom,"lobby:1",Stage::Preparing);
    assert(first && model.pending && model.visible);
    assert(model.advance(first,Stage::Loading));
    assert(model.begin(Source::Custom,"lobby:1",Stage::Preparing)==first);
    assert(model.stage==Stage::Loading); // Duplicate Start cannot rewind progress.
    assert(model.error(first,"Match could not start.",100));
    assert(!model.pending && model.visible && model.notice);
    assert(!model.finish(first)); // Cleanup cannot immediately erase its notice.
    assert(!model.error(first,"late duplicate",1000));
    assert(!model.expire(10099));
    assert(model.expire(10100) && !model.visible);

    const auto retry=model.begin(Source::Custom,"lobby:1",Stage::Preparing);
    assert(retry!=first); // A rejected epoch can be tried again.
    assert(!model.error(first,"stale rejection",11000));
    assert(!model.advance(first,Stage::Waiting));
    assert(!model.finish(first) && model.pending);
    assert(model.finish(retry) && !model.visible);

    const auto normal=model.begin(Source::Dedicated,"ready:1",Stage::Waiting);
    assert(model.finish(normal)); // Explicit Cancel.
    assert(!model.advance(normal,Stage::Waiting) && !model.visible);
    const auto newer=model.begin(Source::Dedicated,"ready:2",Stage::Waiting);
    assert(!model.finish(normal) && model.owns(newer));
    assert(model.error(newer,"Connection lost.",12000));
    const auto practice=model.begin(Source::Practice,"match",Stage::Preparing);
    assert(model.pending && !model.notice);
    assert(!model.expire(99999) && model.visible);
    assert(!model.error(newer,"late connection error",99999));
    assert(model.advance(practice,Stage::Starting));
    assert(model.finish(practice) && !model.visible);
    assert(!model.finish(practice));
    const auto rejected=model.begin(Source::Public,"public-error:1",Stage::Preparing);
    assert(!model.dismissNotice(rejected) && model.owns(rejected));
    assert(model.error(rejected,"Retry this match.",20000));
    assert(!model.dismissNotice(0) && !model.dismissNotice(practice) && model.visible);
    assert(model.dismissNotice(rejected) && !model.visible && !model.notice && model.message.empty());
    assert(!model.dismissNotice(rejected) && !model.expire(99999));
    const auto next=model.begin(Source::Custom,"lobby:2",Stage::Loading);
    assert(!model.dismissNotice(rejected) && model.owns(next));
    assert(model.error(next,"A different failure.",21000));
    assert(!model.dismissNotice(rejected) && model.visible && model.message=="A different failure.");
    assert(model.expire(31000));
    std::cout << "Match loading ownership and notice checks passed\n";
}
