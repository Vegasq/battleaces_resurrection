// Authored accounting/ownership tests only. Never loads or invokes Simulation.
#include "cooperative.cpp"
#include <iostream>
#include <stdexcept>
#include <thread>

namespace {
void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
void healthyLifetime() {
    WaitEpochBudget budget;
    uint64_t total = 0;
    for (unsigned epoch = 0; epoch < 3; ++epoch) {
        WaitEpochScope scope(budget);
        require(budget.pumps == 0 && budget.waits == 1, "fresh outer wait resets budget");
        for (uint64_t index = 0; index < kMaximumPumps / 2; ++index) {
            require(budget.consume(0), "healthy wait admitted");
            ++total;
        }
    }
    require(total > kMaximumPumps && !budget.waits, "lifetime exceeds single-wait cap safely");
}
void stalledEpoch() {
    WaitEpochBudget budget;
    {
        WaitEpochScope scope(budget);
        for (uint64_t index = 0; index < kMaximumPumps; ++index)
            require(budget.consume(0), "last allowed pump admitted");
        require(!budget.consume(0), "stalled wait cannot exceed cap");
        require(budget.pumps == kMaximumPumps, "rejection does not consume budget");
    }
    WaitEpochScope next(budget);
    require(budget.consume(0) && budget.pumps == 1, "next completed wait gets independent budget");
}
void nestedWaits() {
    WaitEpochBudget budget;
    WaitEpochScope outer(budget);
    require(budget.consume(0), "outer consumes");
    {
        WaitEpochScope inner(budget);
        require(budget.waits == 2 && budget.pumps == 1, "nested wait retains outer accounting");
        require(budget.consume(1) && budget.pumps == 2, "nested pump shares counter");
        budget.pumps = kMaximumPumps;
        {
            WaitEpochScope deepest(budget);
            require(!budget.consume(2), "nested wait cannot renew exhausted outer budget");
        }
    }
    require(budget.waits == 1 && !budget.consume(0), "outer retains exhaustion after nested return");
}
void depthLimit() {
    WaitEpochBudget budget;
    WaitEpochScope scope(budget);
    require(budget.consume(kMaximumDepth - 1), "depth63 is admitted");
    require(!budget.consume(kMaximumDepth), "depth64 is refused");
    require(budget.pumps == 1, "depth refusal leaves counter unchanged");
}
void exceptionBalance() {
    WaitEpochBudget budget;
    {
        WaitEpochScope outer(budget);
        require(budget.consume(0), "outer before exception");
        try {
            WaitEpochScope inner(budget);
            require(budget.consume(1), "inner before exception");
            throw 1;
        } catch (int) {}
        require(budget.waits == 1 && budget.pumps == 2, "exception closes inner, preserves outer budget");
    }
    require(!budget.waits, "exception path exits outer epoch");
    WaitEpochScope next(budget);
    require(!budget.pumps, "post-exception next outer wait resets");
}
void ownerRefusal() {
    owner = GetCurrentThreadId();
    stats = Stats{};
    waitEpoch = WaitEpochBudget{};
    require(owned(), "owner accepted");
    std::thread foreign([] { pump(0, nullptr, 0); });
    foreign.join();
    require(stats.error == 1 && stats.foreignThreads == 1, "foreign pump refused before native access");
    require(!stats.pumps && !stats.depth && !waitEpoch.pumps && !waitEpoch.waits,
            "foreign pump cannot change owner-only budget");
}
}

int main() {
    try {
        healthyLifetime();
        stalledEpoch();
        nestedWaits();
        depthLimit();
        exceptionBalance();
        ownerRefusal();
        std::cout << "PASS: 6 authored cooperative wait-epoch groups; no native DLL calls\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
