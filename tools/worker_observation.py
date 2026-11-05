"""External diagnostic worker observations without retaining completed workers."""
import copy
import weakref

class WorkerObservations:
    def __init__(self):
        self.references=[];self.records=[];self.pending=set();self.errors=[]

    def add(self,worker):
        index=len(self.records);reference=weakref.ref(worker)
        self.references.append(reference);self.records.append(None)
        original_close=type(worker).close
        async def close(*args,**kwargs):
            current=reference()
            if current is None:raise RuntimeError('Observed worker disappeared before close')
            try:return await original_close(current,*args,**kwargs)
            finally:
                task=current._cleanup_task
                if task is not None and index not in self.pending:
                    self.pending.add(index)
                    # Retain only until actual cleanup completion. The callback's
                    # scheduled handle then releases this last diagnostic reference.
                    task.add_done_callback(lambda done,owned=current:self.capture(index,owned,done))
        worker.close=close
        return worker

    def capture(self,index,worker,task):
        try:
            if task.cancelled():raise RuntimeError('Observed cleanup was cancelled')
            task.result()
            self.records[index]=copy.deepcopy(dict(pid=worker.pid,exit_code=worker.process.poll(),failure=worker.failure,
                reaped=worker.process.poll() is not None and task.done() and not worker._stderr_thread.is_alive(),
                executable=worker.process.args[0],module_root=worker.process.args[7],game_data_sha256=worker.game_data_sha256,
                simulation_sha256=worker.dll_sha256,ai=worker.ai_info))
        except BaseException as error:self.errors.append(dict(index=index,error=repr(error)))

    def active(self):
        if self.errors:raise RuntimeError('Worker cleanup observation failed: '+repr(self.errors))
        count=0
        for index,reference in enumerate(self.references):
            worker=reference()
            if worker is None:
                if self.records[index] is None and not self.errors:raise RuntimeError('Worker disappeared without cleanup evidence')
            elif worker.process.poll() is None:count+=1
        return count

    def report(self):
        if self.errors or any(row is None for row in self.records):raise RuntimeError('Worker cleanup observation incomplete: '+repr(self.errors))
        return copy.deepcopy(self.records)

    def __len__(self):return len(self.records)
