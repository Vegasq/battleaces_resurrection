#pragma once
#include <atomic>
#include <cstdint>
#include <limits>

// Optional prediction-only observer. Never restored with the native arena.
// Python retains counts by original frame, invalidates them after rewind and
// requires SUM(creates) over confirmed checkpoint -> predicted head <4095.
// A per-step bound or a cumulative match-lifetime bound is insufficient.
namespace ba_entity_guard {
enum class Kind { Create, Hint };
enum class Error : uint64_t {
    None=0, ForeignThread=1, Binding=2, InFlight=3, CounterOverflow=4,
    DirectMasterHint=5, MissingReset=6, CreationLimit=7, IndexLimit=8, Storage=9
};
// Header values only. The native adapter proves the vector's storage belongs
// to one live intercepted allocation BEFORE accepting ownedBytes. No vector
// element needs to be read. Reuse at the index ceiling remains permitted;
// allocating a fresh reserved/null index (or wrapping to0) does not.
inline Error storageError(uint64_t begin,uint64_t end,uint64_t capacity,
                          uint64_t ownedBytes,uint32_t head) noexcept {
    constexpr uint64_t mask=0xfffff;
    if(!begin && !end && !capacity)
        return (head&mask)==mask?Error::None:Error::Storage;
    if(!begin || end<begin || capacity<end || !ownedBytes ||
       (begin&3) || ((end-begin)&3) || ((capacity-begin)&3) || capacity-begin>ownedBytes)
        return Error::Storage;
    const auto count=(end-begin)/4,index=uint64_t(head)&mask;
    if(count>mask || (index==mask && count>=mask))return Error::IndexLimit;
    if(index!=mask && index>=count)return Error::Storage;
    return Error::None;
}
struct Stats {
    uint64_t version=1,error=0,owner=0,world=0,master=0,epoch=0;
    uint64_t creates=0,hints=0,otherCreates=0,otherHints=0,foreign=0,depth=0;
};
static_assert(sizeof(Stats)==96,"entity guard ABI1 contains12 uint64 words");

class State {
public:
    static constexpr uint64_t incarnations=4095;
    explicit State(uint64_t owner):owner_(owner){}
    State(const State&)=delete;State& operator=(const State&)=delete;
    bool bind(uint64_t world,uint64_t master,uint64_t caller) noexcept {
        if(!owned(caller))return false;
        if(error() || !world || !master || master_.load() || depth_)return reject(Error::Binding);
        world_=world;epoch_=creates_=hints_=otherCreates_=otherHints_=0;
        master_.store(master);return true;
    }
    bool reset(uint64_t caller) noexcept {
        if(!owned(caller))return false;
        if(error() || !master_.load())return reject(Error::Binding);
        if(depth_)return reject(Error::InFlight);
        if(epoch_==(std::numeric_limits<uint64_t>::max)())return reject(Error::CounterOverflow);
        ++epoch_;creates_=hints_=otherCreates_=otherHints_=0;return true;
    }
    bool unbind(uint64_t world,uint64_t caller) noexcept {
        if(!owned(caller))return false;
        // Retirement is allowed after a recorded failure, but never in flight.
        if(depth_)return reject(Error::InFlight);
        if(!master_.load() || world!=world_)return reject(Error::Binding);
        master_.store(0);world_=0;return true;
    }
    // Returns whether leave() is required. Inactive transport-only calls forward
    // exactly; foreign callbacks only publish atomic failure diagnostics.
    bool enter(Kind kind,uint64_t registry,uint64_t caller) noexcept {
        const auto master=master_.load();if(!master)return false;
        if(!owned(caller))return false;
        if(depth_==(std::numeric_limits<uint64_t>::max)()){reject(Error::CounterOverflow);return false;}
        ++depth_;
        auto& counter=kind==Kind::Create ? (registry==master?creates_:otherCreates_)
                                         : (registry==master?hints_:otherHints_);
        if(counter==(std::numeric_limits<uint64_t>::max)())reject(Error::CounterOverflow);
        else ++counter;
        if(registry==master) {
            if(!epoch_)reject(Error::MissingReset);
            if(kind==Kind::Hint)reject(Error::DirectMasterHint);
            if(creates_>=incarnations)reject(Error::CreationLimit);
        }
        return true;
    }
    void leave() noexcept {if(depth_)--depth_;else reject(Error::InFlight);}
    bool read(Stats& result,uint64_t caller) noexcept {
        if(!owned(caller))return false;
        if(depth_)return reject(Error::InFlight);
        result={1,error(),owner_,world_,master_.load(),epoch_,creates_,hints_,
                otherCreates_,otherHints_,foreign_.load(),depth_};return true;
    }
    uint64_t error()const noexcept{return error_.load();}
    bool isMaster(uint64_t registry)const noexcept {
        const auto master=master_.load();return master && registry==master;
    }
    void unsupported(Error value) noexcept {if(value!=Error::None)reject(value);}
private:
    bool reject(Error value) noexcept {
        uint64_t expected=0;error_.compare_exchange_strong(expected,static_cast<uint64_t>(value));return false;
    }
    bool owned(uint64_t caller) noexcept {
        if(caller==owner_)return true;
        foreign_.fetch_add(1);return reject(Error::ForeignThread);
    }
    const uint64_t owner_;
    std::atomic<uint64_t> error_{0},foreign_{0},master_{0};
    uint64_t world_=0,epoch_=0,creates_=0,hints_=0,otherCreates_=0,otherHints_=0,depth_=0;
};
}
