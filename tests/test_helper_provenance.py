"""Declared source/DLL receipt binding and explicit immutable historical inputs."""
import copy,json,subprocess,unittest,stat
from unittest import mock
from pathlib import Path
from tools import helper_provenance as h
from tools.package_integrity import PackageError
from tests.test_credentials import private_test_folder,remove_test_folder


class HelperProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.root=private_test_folder('helper-provenance-')
        (self.root/'client_patch/src').mkdir(parents=True)
        (self.root/h.SCRIPT).write_bytes(b'Write-Output "authored"\n')
        (self.root/'client_patch/src/example.cpp').write_bytes(b'int authored() { return 1; }\n')
        self.helper=self.root/'authored-helper.dll';self.data=b'authored helper bytes'
        self.helper.write_bytes(self.data)
        self.receipt=dict(schema=1,helper_sha256=h.sha(self.data),source_sha256={name:h.sha(value) for name,value in h.current_sources(self.root).items()},
            sources_unchanged_during_build=True,compiler_path=str(self.root/'private-source-folder/compiler.exe'),compiler_sha256='a'*64,sdk_version='10.0.26100.0')
        self.write(self.receipt)
    def tearDown(self):
        # Git marks its OWN authored object files read-only on Windows.
        self.root.resolve().relative_to(Path(__file__).resolve().parents[1]/'local/test-runs')
        for path in (self.root/'.git').rglob('*'):
            if path.is_file() and not path.is_symlink():path.chmod(stat.S_IREAD|stat.S_IWRITE)
        remove_test_folder(self.root)
    def write(self,value):(self.root/'helper-build.json').write_text(json.dumps(value))
    def validate(self,**kwargs):return h.validate(self.helper,self.data,self.root,**kwargs)

    def test_current_source_and_bytes_bind_without_publishing_machine_path(self):
        value=self.validate()
        self.assertEqual(value['source'],dict(mode='current-worktree',revision=None))
        self.assertEqual(value['source_sha256'],self.receipt['source_sha256'])
        self.assertNotIn('compiler_path',value);self.assertNotIn('private-source-folder',json.dumps(value))

    def test_missing_duplicate_malformed_and_unfinished_receipts_refuse(self):
        path=self.root/'helper-build.json'
        for raw in ('{','[]','{"schema":1,"schema":1}',json.dumps(dict(self.receipt,sources_unchanged_during_build=1)),json.dumps(dict(self.receipt,schema=True))):
            path.write_text(raw)
            with self.subTest(raw=raw[:25]),self.assertRaises(PackageError):self.validate()
        path.unlink()
        with self.assertRaises(PackageError):self.validate()

    def test_wrong_dll_compiler_sdk_or_source_digest_cannot_be_accepted(self):
        for field,value in (('helper_sha256','0'*64),('compiler_sha256','invalid'),('sdk_version','foreign')):
            self.write(dict(self.receipt,**{field:value}))
            with self.subTest(field=field),self.assertRaises(PackageError):self.validate()
        changed=copy.deepcopy(self.receipt);changed['source_sha256'][h.SCRIPT]='0'*64;self.write(changed)
        with self.assertRaisesRegex(PackageError,'source differs'):self.validate()

    def test_missing_extra_source_or_uncommitted_edit_refuses(self):
        original=self.receipt
        for name in (h.SCRIPT,'client_patch/src/extra.hpp'):
            value=copy.deepcopy(original)
            if name==h.SCRIPT:value['source_sha256'].pop(name)
            else:value['source_sha256'][name]='b'*64
            self.write(value)
            with self.subTest(name=name),self.assertRaises(PackageError):self.validate()
        self.write(original);(self.root/'client_patch/src/example.cpp').write_bytes(b'int different() { return 2; }\n')
        with self.assertRaisesRegex(PackageError,'source differs'):self.validate()

    def test_source_path_traversal_or_foreign_directory_refuses(self):
        for name in ('../outside.cpp','client_patch/src/../../outside.cpp','server/foreign.cpp'):
            value=copy.deepcopy(self.receipt);value['source_sha256'][name]='b'*64;self.write(value)
            with self.subTest(name=name),self.assertRaises(PackageError):self.validate()

    def test_current_checkpoint_inputs_are_required_and_source_bound(self):
        folder=self.root/'client_patch/checkpoint';folder.mkdir()
        header=folder/'owned.hpp';header.write_bytes(b'// authored checkpoint input\n')
        with self.assertRaisesRegex(PackageError,'inventory differs'):self.validate()
        receipt=copy.deepcopy(self.receipt)
        receipt['source_sha256']={name:h.sha(data) for name,data in h.current_sources(self.root).items()}
        self.write(receipt);self.validate()
        header.write_bytes(b'// changed checkpoint input\n')
        with self.assertRaisesRegex(PackageError,'source differs'):self.validate()

    def test_pinned_inventory_follows_ancestor_build_script_not_present_checkpoint_files(self):
        folder=self.root/'client_patch/checkpoint';folder.mkdir()
        (folder/'owned.hpp').write_bytes(b'// authored checkpoint input\n')
        def git(*args):
            return subprocess.check_output(['git','-C',str(self.root),*args],stderr=subprocess.PIPE)
        git('init');git('config','user.name','Authored test');git('config','user.email','authored@example.invalid')
        git('add','client_patch');git('commit','-m','authored src-only build')
        legacy=git('rev-parse','HEAD').decode().strip()
        _,sources=h.git_sources(self.root,legacy)
        self.assertNotIn('client_patch/checkpoint/owned.hpp',sources)
        (self.root/h.SCRIPT).write_bytes(b"$paths=@('src','checkpoint')\n")
        git('add',h.SCRIPT);git('commit','-m','authored expanded build')
        modern=git('rev-parse','HEAD').decode().strip()
        _,sources=h.git_sources(self.root,modern)
        self.assertIn('client_patch/checkpoint/owned.hpp',sources)
        # The exact old helper is still accepted only with its explicit ancestor.
        _,old=h.git_sources(self.root,legacy)
        value=copy.deepcopy(self.receipt);value['source_sha256']={n:h.sha(d) for n,d in old.items()}
        self.write(value);self.validate(revision=legacy)
        with self.assertRaisesRegex(PackageError,'inventory differs'):self.validate()

    def test_pinned_crlf_variant_is_exact_and_never_used_for_current_source(self):
        sources=h.current_sources(self.root);value=copy.deepcopy(self.receipt)
        value['source_sha256']['client_patch/src/example.cpp']=h.sha(sources['client_patch/src/example.cpp'].replace(b'\n',b'\r\n'));self.write(value)
        with self.assertRaises(PackageError):self.validate()
        with mock.patch.object(h,'git_sources',return_value=('f'*40,sources)):
            proof=self.validate(revision='f'*40)
            self.assertEqual(proof['source_line_endings'],{'client_patch/src/example.cpp':'git-lf-to-crlf'})
            value['source_sha256']['client_patch/src/example.cpp']='0'*64;self.write(value)
            with self.assertRaises(PackageError):self.validate(revision='f'*40)

    def test_real_git_snapshot_resolves_ancestor_without_checkout_or_accepting_options(self):
        repo=Path(__file__).resolve().parents[1]
        head=subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD'],text=True).strip()
        revision,sources=h.git_sources(repo,head[:12])
        self.assertEqual(revision,head);self.assertIn(h.SCRIPT,sources)
        self.assertTrue(all(h.helper_source(name) for name in sources))
        for invalid in ('--all','HEAD','main','../file'):
            with self.subTest(invalid=invalid),self.assertRaises(PackageError):h.git_sources(repo,invalid)


if __name__=='__main__':unittest.main()
