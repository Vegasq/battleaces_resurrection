// Inert owned-process control: confirm a Windows file API hook is ready before resume.
const api = Process.getModuleByName('kernel32.dll').getExportByName('CreateFileW');
let calls = 0;
Interceptor.attach(api, {
  onEnter() {
    calls++;
    if (calls === 1) send({kind: 'first-create-file', pid: Process.id});
  }
});
send({kind: 'ready', pid: Process.id, hook: 'CreateFileW'});
