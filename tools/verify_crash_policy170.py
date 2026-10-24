"""Owned crash/normal-Quit lifetime owner; observer qualification is separate."""
from pathlib import Path
import argparse,hashlib,json,os,secrets,struct,subprocess,time,traceback
from tools.native_crash_gate import publish_arm,ready_saved_mode,validate_trigger,wait_for_crash_exit
from tools.owned_suspended_launch import SuspendedChild
from tools.owned_job_tracker import OwnedJobTracker
from tools.owned_process_directory import snapshot
from tools.frida_crash_policy170 import build_source
from tools.verify_unified_startup import shared_state
from tools.helper_provenance import validate
parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['crash','quit'],required=True);parser.add_argument('--output',required=True);args=parser.parse_args()
root=Path(__file__).resolve().parents[1];out=(root/args.output).resolve()
assert out.parent==root/'local' and out.name.startswith('crash170-')
out.mkdir(exist_ok=False)
game=root/'local/r169g';profile='nativestest_crash169_'+secrets.token_hex(6)
folder=game/'.battleaces-resurrection/profiles'/profile
assert not folder.exists();(out/'tmp').mkdir()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def save(n,v):(out/n).write_text(json.dumps(v,indent=2)+'\n')
names=('Battle Aces.exe','GameAssembly.dll','UnityPlayer.dll','BattleAcesOffline.dll',
 'Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/chrome_elf.dll',
 'Battle Aces_Data/Plugins/x86_64/VuplexWebViewChromium/libcef.dll')
def files(game):return {n:sha(game/n) for n in names}
sources=[root/'tools/frida_crash_policy170.py',root/'tools/native_crash_gate.py',root/'tools/frida_native_crash.py',root/'tools/frida_attribution_cwd.py',root/'tools/frida_attribution_paths.py',
 root/'tools/frida_attribution_clock.py',root/'tools/frida_attribution_source.py',root/'tools/owned_suspended_launch.py',
 root/'tools/owned_job_tracker.py',root/'tools/owned_process_directory.py',Path(__file__),root/'client_patch/build.ps1']
sources+=list((root/'client_patch/src').rglob('*.cpp'))+list((root/'client_patch/src').rglob('*.hpp'))
source_hashes=lambda:{p.relative_to(root).as_posix():sha(p) for p in sources}
shared=Path.home()/'AppData/LocalLow/Uncapped Games/Battle Aces/gameconfig-localuser.toml'
report=dict(passed=False,profile=profile,game=str(game),components_before=files(game),current166_before=files(root/'local/r134g'),
 shared_before=shared_state(shared),source_before=source_hashes(),visible_acceptance=False,physical_input=False,
 system_dbghelp_before=sha(Path(os.environ['SystemRoot'])/'System32/dbghelp.dll'))
report['verdict_scope']='owned lifetime and preserved inputs; requires separate observer evidence review'
child=tracker=None;started=time.monotonic()
def wait(n,seconds=240):
 deadline=time.monotonic()+seconds
 while not(out/n).exists():
  if child.poll() is not None:raise RuntimeError('game exited before '+n)
  tracker.observe()
  if time.monotonic()>deadline:raise TimeoutError(n)
  time.sleep(.02)
 return json.loads((out/n).read_bytes())
def log():
 p=game/'investigation/runtime'/f'dedicated-native-{child.pid}.log'
 return p.read_text(encoding='utf-8') if p.exists() else ''
try:
 if report['components_before']['UnityPlayer.dll']!='a53b0c613a86c737b7caa7588c7c93ae20d5d5700f9321a406df9dcca8e32a7f':
  raise ValueError('Pinned recipe23 Unity image differs')
 if sha(root/'local/crash169-preflight-source01/selected-bodies.json')!='fbf9e440d44f11a3a37fdfbc206def60fe992125942a3e049583432217e31f16':
  raise ValueError('Pinned native body inventory differs')
 validate(root/'build/helper-crash169-fix01/BattleAcesOffline.dll',(game/'BattleAcesOffline.dll').read_bytes(),root)
 (game/'investigation/runtime').mkdir(parents=True,exist_ok=True)
 command=[str(game/'Battle Aces.exe'),'-offline-practice','-practice-ai-experimental','-local-profile='+profile,
  '-player-name=Native crash169','-telemetry-audit','-native-crash-probe',
  '-screen-fullscreen','0','-screen-width','960','-screen-height','540','-logFile',str(out/'game.log')]
 if args.mode=='quit':
  command.remove('-native-crash-probe');command+=['-native-quit-smoke','-native-quit-mode=confirm']
 report['mode']=args.mode
 report['command']=command
 env={'TEMP':str(out/'tmp'),'TMP':str(out/'tmp'),'_NT_SYMBOL_PATH':'','_NT_ALT_SYMBOL_PATH':'','_NT_ALTERNATE_SYMBOL_PATH':''}
 old={n:os.environ.get(n) for n in env};os.environ.update(env)
 info=subprocess.STARTUPINFO();info.dwFlags|=subprocess.STARTF_USESHOWWINDOW;info.wShowWindow=0
 try:child=SuspendedChild.create(command,cwd=game,startupinfo=info,creationflags=subprocess.CREATE_NO_WINDOW)
 finally:
  for n,v in old.items():
   if v is None:os.environ.pop(n,None)
   else:os.environ[n]=v
 report['child_environment_overrides']=env
 tracker=OwnedJobTracker(child);tracker.observe();cwd=snapshot(child,allow_uninitialized=True)
 report['cwd_initial']=cwd
 data=(game/'UnityPlayer.dll').read_bytes();pe=struct.unpack_from('<I',data,0x3c)[0]
 count,opt=struct.unpack_from('<H',data,pe+6)[0],struct.unpack_from('<H',data,pe+20)[0]
 sections=[struct.unpack_from('<IIII',data,pe+24+opt+i*40+8) for i in range(count)]
 def bodyhash(start,end):
  for virtualsize,rva,rawsize,offset in sections:
   if rva<=start<end<=rva+rawsize:return hashlib.sha256(data[offset+start-rva:offset+end-rva]).hexdigest()
  raise ValueError('native body outside raw section')
 bodies=[dict(rva=int(b['start'],16),size=int(b['end'],16)-int(b['start'],16),sha256=bodyhash(int(b['start'],16),int(b['end'],16)))
  for b in json.loads((root/'local/crash169-preflight-source01/selected-bodies.json').read_bytes())]
 config=dict(image=str(game/'Battle Aces.exe'),runId=secrets.token_hex(16),fileRoots=[str(game/'.battleaces-resurrection'),str(game/'investigation/runtime'),str(out),str(game/'sim.log'),str(game/'fuzzylogicai.log')],eventLimit=4096)
 native=dict(module=str(game/'UnityPlayer.dll'),bodies=bodies,armFile=str(folder/'native-crash169.arm'))
 (out/'observer.js').write_text(build_source(config,dict(pid=child.pid,pebAddress=cwd['pebAddress']),native),encoding='utf-8')
 report.update(config=config,native=native,pid=child.pid,thread=child.tid,observer_sha256=sha(out/'observer.js'))
 save('request.json',dict(start=dict(mode='attach',device_id='local',pid=child.pid),script=dict(source_kind='file',path=str(out/'observer.js'))))
 save('inputs.json',report)
 attached=wait('rea-start.json')['structuredContent'];loaded=wait('rea-load.json')['structuredContent']
 assert attached['pid']==child.pid and attached['mode']=='attach'
 session=attached['session_id'];assert loaded['parameters']['session_id']==session
 value=loaded['normalized_result'];assert value['source_sha256']==report['observer_sha256'] and not value['messages_truncated']
 assert not any(m['type']=='error' for m in value['messages'])
 release=wait('release.json');assert release==dict(pid=child.pid,session_id=session,observer_sha256=report['observer_sha256'])
 child.resume();save('resume.json',child.receipt)
 if args.mode=='crash':
  deadline=time.monotonic()+90
  while 'NATIVE CRASH ready:' not in log():
   tracker.observe()
   if child.poll() is not None or time.monotonic()>deadline or 'NATIVE CRASH refused:' in log():raise RuntimeError('native preflight did not become ready')
   time.sleep(.02)
  report['saved_mode']=saved_mode=ready_saved_mode(log(),child.tid)
  assert not(folder/'native-crash169.arm').exists();report['cwd_ready']=snapshot(child)
  save('ready.json',dict(pid=child.pid,profile=profile,native_log=log(),cwd=report['cwd_ready'],observer_sha256=report['observer_sha256']))
  assert source_hashes()==report['source_before'] and files(game)==report['components_before']
  assert files(root/'local/r134g')==report['current166_before'] and shared_state(shared)==report['shared_before']
  arm=publish_arm(folder);report['arm_sha256']=sha(arm);report['arm_published']=True
  wait_for_crash_exit(child,tracker,log,saved_mode=saved_mode);validate_trigger(log(),child.tid,saved_mode=saved_mode)
 else:
  deadline=time.monotonic()+90
  while child.poll() is None:
   tracker.observe()
   if time.monotonic()>deadline:raise TimeoutError('original normal Quit deadline')
   time.sleep(.005)
 report.update(exit_code=child.poll(),tracker=tracker.settle(timeout=5))
 if report['tracker']['final_accounting']!=dict(total=1,active=0,terminated=0):
  raise ValueError('Natural root-only lifetime required')
except BaseException as error:report.update(error=repr(error),traceback=traceback.format_exc())
finally:
 if tracker:report['tracker_before_cleanup']=tracker.report();report['tracker_closed']=tracker.close()
 if child:
  child.close();report['launch']=child.receipt;report['native_log']=log()
 report.update(components_after=files(game),current166_after=files(root/'local/r134g'),shared_after=shared_state(shared),source_after=source_hashes(),elapsed_seconds=time.monotonic()-started,system_dbghelp_after=sha(Path(os.environ['SystemRoot'])/'System32/dbghelp.dll'))
 report['passed']=not report.get('error') and report.get('exit_code')==(0xc0000005 if args.mode=='crash' else 0) and report.get('tracker',{}).get('complete') is True and \
  report['launch']['forced_cleanup'] is False and report['launch']['owned_process_reaped'] is True and \
  report['components_before']==report['components_after'] and report['current166_before']==report['current166_after'] and \
  report['shared_before']==report['shared_after'] and report['source_before']==report['source_after'] and report['system_dbghelp_before']==report['system_dbghelp_after']
 save('verification.json',report);print(json.dumps({k:report[k] for k in ('passed','exit_code','error','elapsed_seconds') if k in report}))
raise SystemExit(0 if report['passed'] else 1)
