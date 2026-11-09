#include "page_checkpoint.hpp"
#include <cstring>
#include <functional>
#include <iostream>

namespace p=ba_page_checkpoint;
static void check(bool value,const char* message){if(!value)throw std::runtime_error(message);}
static void rejects(const std::function<void()>& action) {
    bool failed=false;try{action();}catch(const std::runtime_error&){failed=true;}
    check(failed,"expected checkpoint rejection missing");
}
struct Arena {
    static constexpr size_t reserve=64*1024;
    uint8_t* data=nullptr;
    explicit Arena(bool watched=true) {
        DWORD options=MEM_RESERVE;if(watched)options|=MEM_WRITE_WATCH;
        data=static_cast<uint8_t*>(VirtualAlloc(nullptr,reserve,options,PAGE_READWRITE));
        check(data!=nullptr,"test reservation failed");
    }
    ~Arena(){if(data)VirtualFree(data,0,MEM_RELEASE);}
    void commit(size_t bytes){check(VirtualAlloc(data,bytes,MEM_COMMIT,PAGE_READWRITE)==data,"arena commit failed");}
    Arena(const Arena&)=delete;Arena& operator=(const Arena&)=delete;
};
static void bytes(const Arena& arena,size_t offset,size_t amount,uint8_t expected) {
    for(size_t index=0;index<amount;++index)check(arena.data[offset+index]==expected,"restored byte mismatch");
}
static void incrementalAndVersionRestore() {
    Arena arena;arena.commit(Arena::reserve);std::memset(arena.data,0x11,Arena::reserve);
    p::Store store(arena.data,Arena::reserve,4*Arena::reserve);
    const size_t page=store.pageSize();check(Arena::reserve%page==0,"test page size unsupported");
    const auto first=store.capture(123,Arena::reserve);
    check(store.stats().lastCaptureCopiedBytes==Arena::reserve,"first capture did not copy baseline once");
    const auto idle=store.capture(123,Arena::reserve);
    check(store.stats().lastCaptureCopiedBytes==0,"untouched capture copied pages");
    arena.data[9]=0x22;arena.data[page+3]=0x33;
    const auto second=store.capture(321,Arena::reserve);
    check(store.stats().lastCaptureCopiedBytes==2*page,"incremental capture copied untouched pages");
    // GetWriteWatch is quiet after capture, so only map-version differences
    // identify the older two pages that need restoration.
    auto position=store.restore(first,Arena::reserve);
    check(position.high==123 && position.committedExtent==Arena::reserve,"logical metadata did not restore");
    check(store.stats().lastRestoreCopiedBytes==2*page,"older restore missed changed versions");
    bytes(arena,0,Arena::reserve,0x11);
    check(store.restore(second,Arena::reserve).high==321,"newer checkpoint high was lost");
    check(arena.data[9]==0x22 && arena.data[page+3]==0x33,"newer versions not restored");
    check(store.stats().lastRestoreCopiedBytes==2*page,"newer restore copied untouched pages");
    arena.data[2*page+4]=0x99;arena.data[2*page+5]=0x88;
    store.restore(second,Arena::reserve);
    check(store.stats().lastRestoreCopiedBytes==page,"uncaptured repeated writes were not one dirty page");
    bytes(arena,2*page,page,0x11);
    store.restore(second,Arena::reserve);
    check(store.stats().lastRestoreCopiedBytes==0,"restore writes polluted the next write-watch interval");
    store.capture(321,Arena::reserve);
    check(store.stats().lastCaptureCopiedBytes==0,"restore writes caused a new capture copy");
    store.drop(idle);check(store.stats().checkpointCount==3,"drop did not remove exactly one checkpoint");
    rejects([&]{store.restore(idle,Arena::reserve);});
}
static void mixedDirtyAndChangedVersions() {
    Arena arena;arena.commit(Arena::reserve);std::memset(arena.data,0x10,Arena::reserve);
    p::Store store(arena.data,Arena::reserve,4*Arena::reserve);const size_t page=store.pageSize();
    const auto old=store.capture(100,Arena::reserve);
    arena.data[0]=0x20;const auto newer=store.capture(200,Arena::reserve);
    arena.data[page]=0x30;arena.data[0]=0x40;
    store.restore(old,Arena::reserve);
    check(store.stats().lastRestoreCopiedBytes==2*page,"dirty/version union missed or duplicated a page");
    bytes(arena,0,Arena::reserve,0x10);
    store.restore(newer,Arena::reserve);check(arena.data[0]==0x20 && arena.data[page]==0x10,"newer capture included later dirty data");
}
static void growthAndLogicalRollback() {
    Arena arena;SYSTEM_INFO info{};GetSystemInfo(&info);const size_t page=info.dwPageSize;
    arena.commit(2*page);std::memset(arena.data,0x51,2*page);
    p::Store store(arena.data,Arena::reserve,4*Arena::reserve);
    const auto old=store.capture(page+7,2*page);
    arena.commit(6*page);std::memset(arena.data+2*page,0x61,4*page);
    const auto grown=store.capture(5*page+9,6*page);
    check(store.stats().lastCaptureCopiedBytes==4*page,"growth recopied unchanged baseline pages");
    const auto result=store.restore(old,6*page);
    check(result.high==page+7 && result.committedExtent==2*page,"growth logical extent did not roll back");
    check(store.stats().lastRestoreCopiedBytes==0 && store.stats().physicalCommittedHighwater==6*page,
          "older growth restore rewrote unchanged pages or lost physical high-water");
    // Restoring newer must copy pages that are outside the older logical map,
    // even though their physical bytes happen to still contain the right data.
    store.restore(grown,6*page);check(store.stats().lastRestoreCopiedBytes==4*page,"newer logical growth versions not restored");
    bytes(arena,2*page,4*page,0x61);
    store.restore(old,6*page);arena.data[4*page]=0x71;
    store.restore(old,6*page); // Clears watch bits outside the target extent.
    const auto regrown=store.capture(5*page,6*page);
    check(store.stats().lastCaptureCopiedBytes==4*page,"quiet newly logical pages were not captured");
    arena.data[4*page]=0x81;store.restore(regrown,6*page);
    check(arena.data[4*page]==0x71,"regrowth snapshot reused a stale inactive version");
    // Growth can happen and be rolled back before it was ever captured.
    arena.commit(8*page);std::memset(arena.data+6*page,0xA1,2*page);
    const auto previousCopies=store.stats().restoreCopiedBytes;
    const auto older=store.restore(old,8*page);
    check(older.committedExtent==2*page && store.stats().physicalCommittedHighwater==8*page,
          "uncaptured growth was not tracked on restore");
    check(store.stats().restoreCopiedBytes==previousCopies,"inactive uncaptured growth copied irrelevant pages");
}
static void sharedStorageAndBudget() {
    Arena arena;arena.commit(Arena::reserve);std::memset(arena.data,0x91,Arena::reserve);
    SYSTEM_INFO info{};GetSystemInfo(&info);const size_t page=info.dwPageSize;
    p::Store store(arena.data,Arena::reserve,Arena::reserve+2*page);
    const auto baseline=store.capture(1,Arena::reserve);
    arena.data[0]=0x92;const auto first=store.capture(2,Arena::reserve);
    arena.data[0]=0x93;const auto second=store.capture(3,Arena::reserve);
    check(store.stats().uniqueSavedBytes==Arena::reserve+2*page,"page batches not shared/accounted");
    arena.data[page]=0x94;
    rejects([&]{store.capture(4,Arena::reserve);});
    check(!store.failed() && store.stats().checkpointCount==3,"budget refusal mutated snapshot ownership");
    store.drop(first);
    check(store.stats().uniqueSavedBytes==Arena::reserve+page,"drop did not release unreferenced page batch");
    const auto third=store.capture(4,Arena::reserve);
    check(store.stats().lastCaptureCopiedBytes==page,"budget rejection lost dirty watch bits");
    store.drop(baseline);store.drop(second);store.drop(third);
    check(store.stats().checkpointCount==0 && store.stats().uniqueSavedBytes==Arena::reserve+2*page,
          "current baseline ownership was not retained after dropping all saved IDs");
}
static void checkpointCountAndBounds() {
    Arena arena;arena.commit(Arena::reserve);std::memset(arena.data,0,Arena::reserve);
    p::Store store(arena.data,Arena::reserve,2*Arena::reserve);
    uint64_t first=0;
    for(size_t index=0;index<p::Store::maximumCheckpoints;++index) {
        const auto id=store.capture(index,Arena::reserve);if(!index)first=id;
    }
    check(store.stats().checkpointCount==16 && store.stats().captureCopiedBytes==Arena::reserve,
          "16 unchanged checkpoints did not share the baseline");
    rejects([&]{store.capture(17,Arena::reserve);});store.drop(first);
    const auto replacement=store.capture(17,Arena::reserve);
    check(replacement>16 && store.stats().checkpointCount==16,"drop did not reopen a checkpoint slot");
    rejects([&]{store.capture(Arena::reserve+1,Arena::reserve);});
    rejects([&]{store.restore(999,Arena::reserve);});
    rejects([&]{store.restore(replacement,Arena::reserve+store.pageSize());});
    rejects([&]{p::Store invalid(arena.data,Arena::reserve,Arena::reserve,17);});
    rejects([&]{p::Store invalid(arena.data+1,Arena::reserve,Arena::reserve);});
    rejects([&]{p::Store invalid(arena.data,p::Store::maximumReservation+store.pageSize(),Arena::reserve);});
    Arena plain(false);plain.commit(Arena::reserve);
    p::Store unsupported(plain.data,Arena::reserve,Arena::reserve);
    rejects([&]{unsupported.capture(1,Arena::reserve);});
    check(unsupported.failed(),"missing MEM_WRITE_WATCH did not fail closed");
    rejects([&]{unsupported.capture(1,Arena::reserve);});
}
int main() {
    try {
        incrementalAndVersionRestore();mixedDirtyAndChangedVersions();growthAndLogicalRollback();
        sharedStorageAndBudget();checkpointCountAndBounds();
        std::cout<<"page checkpoint: 5 native write-watch scenario groups PASS\n";return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
