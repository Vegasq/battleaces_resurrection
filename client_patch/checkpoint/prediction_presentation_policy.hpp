#pragma once
#include <cstdint>
#include <optional>
#include <stdexcept>

// Isolated experiment policy. This does not hook GameAssembly or dispatch an
// IL2CPP event. The caller supplies validated, current-match canonical evidence.
namespace ba_prediction_presentation {
inline void require(bool value,const char* message) {
    if(!value)throw std::runtime_error(message);
}

// Identity fields of original GameCompletedEventArgs. SimStats/event objects
// stay with the integration owner and must come from confirmed authority.
struct Terminal {
    int32_t gameOverFrame=-1;
    uint32_t winningAllianceId=0,armyConcededFlag=0;
    uint64_t gameOverChecksum=0;
};
inline bool operator==(const Terminal& left,const Terminal& right) {
    return left.gameOverFrame==right.gameOverFrame &&
        left.winningAllianceId==right.winningAllianceId &&
        left.armyConcededFlag==right.armyConcededFlag &&
        left.gameOverChecksum==right.gameOverChecksum;
}
inline bool operator!=(const Terminal& left,const Terminal& right){return !(left==right);}

class TerminalGate {
public:
    // A strictly new generation prevents a delayed old-match callback from
    // becoming current after a rematch. Generation zero is never active.
    void reset(uint64_t generation) {
        require(generation>generation_,"presentation generation must advance");
        generation_=generation;active_=true;emitted_=false;
        confirmedFrame_=presentedFrame_=-1;
        confirmedTerminal_.reset();presentedTerminal_.reset();
    }
    void invalidate() {
        active_=false;confirmedTerminal_.reset();presentedTerminal_.reset();
    }
    bool active(uint64_t generation)const{return active_ && generation==generation_;}
    bool emitted()const{return emitted_;}
    int32_t confirmedFrame()const{return confirmedFrame_;}
    int32_t presentedFrame()const{return presentedFrame_;}

    // Call only after actual ordinary publication, not merely after SimStep.
    // Corrections advance the physical head; same-frame contradictory state is
    // deliberately unsupported by the initial monotonic-publication design.
    bool presented(uint64_t generation,int32_t frame,std::optional<Terminal> terminal) {
        if(!active(generation))return false;
        validate(frame,terminal);
        require(frame>=presentedFrame_,"presented frame regressed");
        if(frame==presentedFrame_) {
            require(terminal==presentedTerminal_,"same-frame presentation changed");
            return true;
        }
        if(emitted_)require(terminal==confirmedTerminal_,"published terminal event cannot be undone");
        presentedFrame_=frame;presentedTerminal_=terminal;return true;
    }

    // This is a fully processed contiguous authority watermark, never a
    // speculative head or an unvalidated command receipt. It may advance over
    // a processed prefix. A terminal payload is the canonical state at frame.
    bool confirmed(uint64_t generation,int32_t frame,std::optional<Terminal> terminal) {
        if(!active(generation))return false;
        validate(frame,terminal);
        require(frame>=confirmedFrame_,"confirmed frame regressed");
        if(frame==confirmedFrame_) {
            require(terminal==confirmedTerminal_,"same-frame authority changed");
            return true;
        }
        if(confirmedTerminal_)
            require(terminal==confirmedTerminal_,"confirmed terminal state changed");
        confirmedFrame_=frame;confirmedTerminal_=terminal;return true;
    }

    // Poll on BOTH authority confirmation and ordinary publication. Waiting
    // only for an ended transition loses the event when authority arrives late
    // and the two most recent displayed frames are already both ended.
    std::optional<Terminal> takeReady(uint64_t generation) {
        if(!active(generation) || emitted_ || !confirmedTerminal_ ||
           presentedTerminal_!=confirmedTerminal_ ||
           presentedFrame_<confirmedTerminal_->gameOverFrame)return std::nullopt;
        emitted_=true;return confirmedTerminal_;
    }
private:
    static void validate(int32_t frame,const std::optional<Terminal>& terminal) {
        require(frame>=0,"presentation frame must be nonnegative");
        if(terminal)require(terminal->gameOverFrame>=0 && terminal->gameOverFrame<=frame,
                            "terminal frame is outside observed history");
    }
    uint64_t generation_=0;
    bool active_=false,emitted_=false;
    int32_t confirmedFrame_=-1,presentedFrame_=-1;
    std::optional<Terminal> confirmedTerminal_,presentedTerminal_;
};

struct ActorIdentity {
    uint32_t entityId=0,unitType=0,armyId=0;
};
enum class ActorDecision { None,Keep,Create,Release,Reload };

// resident must describe the actor originally instantiated, BEFORE its live
// component references are refreshed. Reading both identities from the new
// frame would hide a pooled actor whose entityId was reused after correction.
inline ActorDecision actorDecision(std::optional<ActorIdentity> resident,
                                   std::optional<ActorIdentity> current) {
    if(!resident)return current?ActorDecision::Create:ActorDecision::None;
    if(!current)return ActorDecision::Release;
    require(resident->entityId==current->entityId,"actor reconciliation needs one entity ID");
    return resident->unitType!=current->unitType || resident->armyId!=current->armyId
        ?ActorDecision::Reload:ActorDecision::Keep;
}
}
