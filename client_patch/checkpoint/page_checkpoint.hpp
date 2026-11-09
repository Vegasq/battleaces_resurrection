#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <algorithm>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

// Isolated experiment, not linked into the game. The caller owns a contiguous
// MEM_WRITE_WATCH reservation, commits pages from its base, and NEVER decommits
// or releases them while Store lives. Calls and arena writers must be quiescent
// and serialized. This does not capture allocator/TLS/OS/thread state.
namespace ba_page_checkpoint {
struct Position { size_t high=0,committedExtent=0; };
struct Stats {
    uint64_t captures=0,restores=0,drops=0;
    uint64_t captureCopiedBytes=0,restoreCopiedBytes=0;
    uint64_t lastCaptureCopiedBytes=0,lastRestoreCopiedBytes=0;
    uint64_t lastCaptureSkippedPages=0,lastRestoreSkippedPages=0;
    uint64_t lastCaptureDirtyPages=0,lastRestoreDirtyPages=0;
    uint64_t lastCaptureMicros=0,lastRestoreMicros=0;
    size_t uniqueSavedBytes=0,checkpointCount=0;
    size_t currentHigh=0,logicalCommittedExtent=0,physicalCommittedHighwater=0;
};

class Store {
public:
    static constexpr size_t maximumCheckpoints=16;
    static constexpr size_t maximumReservation=size_t(512)<<20;
    Store(void* arena,size_t reservedBytes,size_t maxUniqueSavedBytes,
          size_t checkpointLimit=maximumCheckpoints)
        :base_(static_cast<uint8_t*>(arena)),reserved_(reservedBytes),limit_(checkpointLimit),
         budget_(std::make_shared<Budget>()) {
        SYSTEM_INFO info{};GetSystemInfo(&info);pageSize_=info.dwPageSize;
        require(base_ && reserved_ && reserved_<=maximumReservation && pageSize_ &&
                reinterpret_cast<uintptr_t>(base_)%pageSize_==0 && reserved_%pageSize_==0,
                "page checkpoint needs a page-aligned reservation");
        require(limit_>0 && limit_<=maximumCheckpoints,"checkpoint limit must be 1..16");
        require(maxUniqueSavedBytes>0,"saved-page byte budget must be positive");
        budget_->limit=maxUniqueSavedBytes;
        checkpoints_.reserve(limit_);watchAddresses_.resize(reserved_/pageSize_);
        currentMap_=std::make_shared<const PageMap>();
    }
    Store(const Store&)=delete;
    Store& operator=(const Store&)=delete;
    Store(Store&&)=delete;
    Store& operator=(Store&&)=delete;

    uint64_t capture(size_t currentHigh,size_t committedExtent) {
        healthy();extent(committedExtent);
        require(currentHigh<=committedExtent,"arena high exceeds committed extent");
        require(checkpoints_.size()<limit_,"checkpoint count limit reached");
        require(nextId_<(std::numeric_limits<uint64_t>::max)(),"checkpoint IDs exhausted");
        const auto start=Clock::now();observePhysical(committedExtent);
        const auto dirty=dirtyPages();
        const size_t pages=committedExtent/pageSize_;
        std::vector<uint8_t> needed(pages,0);
        for(const auto page:dirty)if(page<pages)needed[page]=1;
        // New logical pages must be captured even if a previous restore reset
        // their OS write bits while they were outside the restored extent.
        for(size_t page=currentMap_->size();page<pages;++page)needed[page]=1;
        size_t copies=0;for(const auto value:needed)copies+=value;

        std::shared_ptr<const PageMap> candidate=currentMap_;
        if(copies || pages!=currentMap_->size()) {
            auto map=std::make_shared<PageMap>(*currentMap_);map->resize(pages);
            if(copies) {
                auto batch=makeBatch(copies);size_t index=0;
                for(size_t page=0;page<pages;++page)if(needed[page]) {
                    std::copy_n(base_+page*pageSize_,pageSize_,batch->bytes.data()+index*pageSize_);
                    (*map)[page]=Page{batch,index++};
                }
            }
            candidate=map;
        }
        // All allocating/failing preparation precedes ResetWriteWatch. Once
        // reset succeeds, the reserved checkpoint vector push cannot allocate.
        Checkpoint saved{nextId_,{currentHigh,committedExtent},candidate};
        resetWatch();currentMap_=std::move(candidate);position_=saved.position;
        checkpoints_.push_back(std::move(saved));const uint64_t result=nextId_++;
        ++stats_.captures;stats_.lastCaptureCopiedBytes=static_cast<uint64_t>(copies)*pageSize_;
        stats_.captureCopiedBytes+=stats_.lastCaptureCopiedBytes;
        stats_.lastCaptureSkippedPages=pages-copies;stats_.lastCaptureDirtyPages=dirty.size();
        stats_.lastCaptureMicros=micros(start);return result;
    }

    // currentCommittedExtent must include growth since the last Store call.
    // Older logical extents are returned, while physical pages remain committed.
    Position restore(uint64_t id,size_t currentCommittedExtent) {
        healthy();extent(currentCommittedExtent);
        const auto found=std::find_if(checkpoints_.begin(),checkpoints_.end(),
                                      [id](const Checkpoint& value){return value.id==id;});
        require(found!=checkpoints_.end(),"checkpoint ID is not retained");
        const auto start=Clock::now();observePhysical(currentCommittedExtent);
        const auto dirty=dirtyPages();
        const auto target=found->pages;const Position result=found->position;
        std::vector<uint8_t> needed(target->size(),0);
        for(const auto page:dirty)if(page<needed.size())needed[page]=1;
        for(size_t page=0;page<target->size();++page)
            if(page>=currentMap_->size() || !same((*currentMap_)[page],(*target)[page]))needed[page]=1;
        // Preparation above does not mutate arena memory. Validate every page
        // before beginning copies; OS watch errors after copying fail terminally.
        for(size_t page=0;page<target->size();++page)
            require((*target)[page].batch!=nullptr,"checkpoint has an uncaptured page");
        size_t copies=0;
        for(size_t page=0;page<target->size();++page)if(needed[page]) {
            const auto& value=(*target)[page];
            std::copy_n(value.batch->bytes.data()+value.index*pageSize_,pageSize_,base_+page*pageSize_);
            ++copies;
        }
        resetWatch();currentMap_=target;position_=result;
        ++stats_.restores;stats_.lastRestoreCopiedBytes=static_cast<uint64_t>(copies)*pageSize_;
        stats_.restoreCopiedBytes+=stats_.lastRestoreCopiedBytes;
        stats_.lastRestoreSkippedPages=target->size()-copies;stats_.lastRestoreDirtyPages=dirty.size();
        stats_.lastRestoreMicros=micros(start);return result;
    }

    void drop(uint64_t id) {
        const auto found=std::find_if(checkpoints_.begin(),checkpoints_.end(),
                                      [id](const Checkpoint& value){return value.id==id;});
        require(found!=checkpoints_.end(),"checkpoint ID is not retained");
        checkpoints_.erase(found);++stats_.drops;
        // Current-version pages remain referenced as the baseline for the next
        // incremental capture even if its saved checkpoint has been dropped.
    }
    Stats stats()const {
        auto result=stats_;result.uniqueSavedBytes=budget_->live;
        result.checkpointCount=checkpoints_.size();result.currentHigh=position_.high;
        result.logicalCommittedExtent=position_.committedExtent;
        result.physicalCommittedHighwater=physicalHighwater_;return result;
    }
    size_t pageSize()const{return pageSize_;}
    bool failed()const{return failed_;}
private:
    using Clock=std::chrono::steady_clock;
    struct Budget {size_t limit=0,live=0;};
    struct Batch {
        std::shared_ptr<Budget> budget;
        std::vector<uint8_t> bytes;
        Batch(std::shared_ptr<Budget> owner,size_t amount):budget(std::move(owner)),bytes(amount) {
            budget->live+=amount;
        }
        ~Batch(){budget->live-=bytes.size();}
        Batch(const Batch&)=delete;
        Batch& operator=(const Batch&)=delete;
    };
    struct Page {std::shared_ptr<const Batch> batch;size_t index=0;};
    using PageMap=std::vector<Page>;
    struct Checkpoint {uint64_t id;Position position;std::shared_ptr<const PageMap> pages;};
    static void require(bool result,const char* message) {
        if(!result)throw std::runtime_error(message);
    }
    void healthy()const{require(!failed_,"page checkpoint store is failed");}
    void extent(size_t value)const {
        require(value<=reserved_ && value%pageSize_==0,"invalid committed extent");
    }
    void observePhysical(size_t value){physicalHighwater_=(std::max)(physicalHighwater_,value);}
    [[noreturn]] void osError(const char* operation,UINT code) {
        failed_=true;throw std::runtime_error(std::string(operation)+" failed: "+std::to_string(code));
    }
    std::vector<size_t> dirtyPages() {
        std::vector<size_t> result;
        if(!physicalHighwater_)return result;
        ULONG_PTR count=static_cast<ULONG_PTR>(watchAddresses_.size());ULONG granularity=0;
        const UINT code=GetWriteWatch(0,base_,physicalHighwater_,watchAddresses_.data(),&count,&granularity);
        if(code)osError("GetWriteWatch",code);
        if(granularity!=pageSize_ || count>watchAddresses_.size())osError("write-watch granularity/count",ERROR_INVALID_DATA);
        result.reserve(static_cast<size_t>(count));
        const auto address=reinterpret_cast<uintptr_t>(base_);
        for(size_t index=0;index<static_cast<size_t>(count);++index) {
            const auto value=reinterpret_cast<uintptr_t>(watchAddresses_[index]);
            if(value<address || value-address>=physicalHighwater_ || (value-address)%pageSize_)
                osError("write-watch page address",ERROR_INVALID_DATA);
            result.push_back((value-address)/pageSize_);
        }
        std::sort(result.begin(),result.end());result.erase(std::unique(result.begin(),result.end()),result.end());
        return result;
    }
    void resetWatch() {
        if(physicalHighwater_) {
            const UINT code=ResetWriteWatch(base_,physicalHighwater_);
            if(code)osError("ResetWriteWatch",code);
        }
    }
    std::shared_ptr<Batch> makeBatch(size_t pages) {
        require(pages<=reserved_/pageSize_,"saved page count exceeds reservation");
        const size_t amount=pages*pageSize_;
        require(budget_->live<=budget_->limit && amount<=budget_->limit-budget_->live,
                "unique saved-page byte budget reached");
        return std::make_shared<Batch>(budget_,amount);
    }
    static bool same(const Page& left,const Page& right) {
        return left.batch==right.batch && left.index==right.index;
    }
    static uint64_t micros(const Clock::time_point& start) {
        return static_cast<uint64_t>(std::chrono::duration_cast<std::chrono::microseconds>(Clock::now()-start).count());
    }
    uint8_t* base_=nullptr;
    size_t reserved_=0,limit_=0,pageSize_=0,physicalHighwater_=0;
    bool failed_=false;
    uint64_t nextId_=1;
    Position position_;
    Stats stats_;
    std::shared_ptr<Budget> budget_;
    std::shared_ptr<const PageMap> currentMap_;
    std::vector<Checkpoint> checkpoints_;
    std::vector<void*> watchAddresses_;
};
}
