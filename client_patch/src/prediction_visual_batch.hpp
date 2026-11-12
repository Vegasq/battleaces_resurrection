#pragma once
#include <cstddef>

// Publication barrier for an already validated correction batch. Resolver or
// writer failure publishes no observation. A sync failure is never retried.
namespace ba_prediction_visual_batch {
template<class Writes,class Prepare,class Apply,class Sync,class Observe>
void publish(Writes& writes,Prepare prepare,Apply apply,Sync sync,Observe observe) {
    size_t changed=0;
    for(const auto& write:writes)if(write.mutate)++changed;
    if(changed)prepare();
    for(auto& write:writes)if(write.mutate)apply(write);
    if(changed)sync(changed);
    for(auto& write:writes)observe(write);
}
}
