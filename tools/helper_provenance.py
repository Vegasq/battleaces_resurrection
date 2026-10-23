"""Validate declared helper build inputs against current or pinned authored text."""
from __future__ import annotations
import hashlib,json,re,subprocess
from pathlib import Path,PurePosixPath
from .audit_repository import inspect_content
from .package_integrity import PackageError,ordinary_file,safe_name

SCRIPT='client_patch/build.ps1'
def sha(data):return hashlib.sha256(data).hexdigest()
def helper_source(name):
    safe_name(name)
    return name==SCRIPT or (name.startswith('client_patch/src/') and PurePosixPath(name).suffix.lower() in ('.cpp','.h','.hpp'))

def current_sources(root):
    names=[SCRIPT]+[path.relative_to(root).as_posix() for path in (root/'client_patch/src').rglob('*') if path.is_file() and path.suffix.lower() in ('.cpp','.h','.hpp')]
    return {name:ordinary_file(root,name).read_bytes() for name in sorted(names)}

def git_sources(root,revision):
    if not isinstance(revision,str) or not re.fullmatch('[0-9a-fA-F]{7,40}',revision):raise PackageError('Helper source revision must be a commit hash')
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.PIPE)
    try:
        commit=git('rev-parse','--verify',revision+'^{commit}').decode().strip()
        if not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('commit identity')
        git('merge-base','--is-ancestor',commit,'HEAD')
        rows=git('ls-tree','-r','-z',commit,'--','client_patch/build.ps1','client_patch/src')
        sources={}
        for row in rows.split(b'\0'):
            if not row:continue
            metadata,name=row.split(b'\t',1);mode,kind,oid=metadata.split();name=name.decode('utf-8')
            if not helper_source(name):continue
            if kind!=b'blob' or mode not in (b'100644',b'100755'):raise ValueError('ordinary source required')
            sources[name]=git('cat-file','blob',oid.decode())
        return commit,sources
    except (subprocess.CalledProcessError,UnicodeError,ValueError):raise PackageError('Cannot bind helper to an ordinary ancestor source tree') from None

def validate(path,data,root,*,revision=None):
    path,root=Path(path),Path(root)
    try:
        receipt_path=ordinary_file(path.parent,'helper-build.json')
        if not 1<=receipt_path.stat().st_size<=128*1024:raise ValueError('receipt size')
        raw=receipt_path.read_bytes()
        def unique(pairs):
            result={}
            for key,value in pairs:
                if key in result:raise ValueError('duplicate receipt field')
                result[key]=value
            return result
        receipt=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique)
        fields={'schema','helper_sha256','source_sha256','sources_unchanged_during_build','compiler_path','compiler_sha256','sdk_version'}
        if type(receipt) is not dict or set(receipt)!=fields or type(receipt['schema']) is not int or receipt['schema']!=1:raise ValueError('schema')
        if receipt['helper_sha256']!=sha(data) or receipt['sources_unchanged_during_build'] is not True:raise ValueError('helper or source drift')
        if not isinstance(receipt['compiler_sha256'],str) or not re.fullmatch('[0-9a-f]{64}',receipt['compiler_sha256']):raise ValueError('compiler digest')
        if not isinstance(receipt['compiler_path'],str) or not 1<=len(receipt['compiler_path'])<=32767:raise ValueError('compiler identity')
        if not isinstance(receipt['sdk_version'],str) or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+',receipt['sdk_version']):raise ValueError('SDK identity')
        declared=receipt['source_sha256']
        if type(declared) is not dict or not 1<=len(declared)<=512 or SCRIPT not in declared:raise ValueError('source inventory')
        if any(not helper_source(name) or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) for name,digest in declared.items()):raise ValueError('source field')
    except (OSError,ValueError,TypeError,AttributeError,KeyError,UnicodeError):raise PackageError('Helper build receipt is missing,malformed or does not match the DLL') from None
    commit,sources=git_sources(root,revision) if revision else (None,current_sources(root))
    if set(sources)!=set(declared):raise PackageError('Helper build receipt source inventory differs; rebuild or explicitly pin its source revision')
    variants={};git_hashes={}
    for name,source in sources.items():
        if inspect_content(name,source):raise PackageError('Helper source audit rejected '+name)
        git_hashes[name]=sha(source)
        if declared[name]==sha(source):continue
        # Legacy Windows worktrees sometimes built CRLF despite Git's LF blob.
        # Reconstruct only that exact byte variant; never ignore arbitrary edits.
        if revision and b'\r' not in source and declared[name]==sha(source.replace(b'\n',b'\r\n')):
            variants[name]='git-lf-to-crlf';continue
        raise PackageError('Helper build receipt source differs: '+name)
    return dict(schema=1,helper_sha256=sha(data),build_receipt_sha256=sha(raw),sources_unchanged_during_build=True,
        source=dict(mode='pinned-git' if revision else 'current-worktree',revision=commit),
        source_sha256=declared,git_source_sha256=git_hashes if revision else None,source_line_endings=variants,
        compiler_sha256=receipt['compiler_sha256'],sdk_version=receipt['sdk_version'])
