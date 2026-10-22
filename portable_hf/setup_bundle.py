#!/usr/bin/env python3
"""Extract verified sources and relocate execution code; task bytes stay fixed."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parent
OLD='/fsx/home/zhiyuan'


def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true',help='Install pinned dependencies into the active Python 3.12+ environment')
    args=parser.parse_args()
    assert sys.version_info>=(3,12),'Use Python 3.12 or newer'
    manifests=[json.loads((ROOT/'WORKSPACE_MANIFEST.json').read_text())]
    if (ROOT/'SUPPLEMENT_MANIFEST.json').exists():manifests.append(json.loads((ROOT/'SUPPLEMENT_MANIFEST.json').read_text()))
    files={}
    for manifest in manifests:
        name=manifest.get('archive_name','workspace.tar.zst')
        assert digest(ROOT/name)==manifest['archive_sha256'],name
        process=subprocess.Popen(['zstd','-dc',str(ROOT/name)],stdout=subprocess.PIPE)
        try:
            with tarfile.open(fileobj=process.stdout,mode='r|') as tar:
                for member in tar:
                    assert member.isfile() and member.name.startswith('workspace/')
                    relative=Path(member.name)
                    assert '..' not in relative.parts and not relative.is_absolute()
                    path=ROOT/relative;path.parent.mkdir(parents=True,exist_ok=True)
                    with tar.extractfile(member) as src,path.open('wb') as dst:shutil.copyfileobj(src,dst)
                    path.chmod(member.mode)
            assert process.wait()==0
        finally:
            if process.poll() is None:process.kill()
        for rel,record in manifest['files'].items():
            assert digest(ROOT/'workspace'/rel)==record['sha256'],rel
            files[rel]=record
    changes={}
    workspace=ROOT/'workspace'
    for rel in files:
        if not rel.endswith('.py'):continue
        # Never modify task instructions, model-visible files, solutions or tests.
        if '/tasks/' in rel or '/sources/terminal-bench-2-1/' in rel:continue
        path=workspace/rel
        text=path.read_text();updated=text.replace(OLD,str(workspace))
        if path.name in ('deep_entry.py','audited_agents.py','swe_entry.py'):
            # All profiles use the same host-side bridge port. Original model
            # generation settings, task data and network restrictions stay fixed.
            updated=updated.replace('31328','31320').replace('31324','31320')
        if path.name=='_swebench_utils.py':
            original='''    ds = load_dataset(
        "princeton-nlp/SWE-bench_Verified",
        split="test",
        cache_dir=cache_dir,
    )'''
            replacement='''    from datasets import Dataset
    local = Path(__file__).resolve().parents[2] / "datasets/princeton-nlp___swe-bench_verified/default/0.0.0/c104f840cc67f8b6eec6f759ebc8b2693d585d4a/swe-bench_verified-test.arrow"
    ds = Dataset.from_file(str(local))'''
            assert original in updated,'Upstream data-loader source changed; inspect before adapting'
            updated=updated.replace(original,replacement)
        if updated!=text:
            path.write_text(updated)
            changes[rel]={'source_sha256':files[rel]['sha256'],'relocated_sha256':digest(path)}
    for rel in files:
        if rel.endswith('.py') and '/tasks/' not in rel and '/sources/terminal-bench-2-1/' not in rel:
            parent=(workspace/rel).parent
            if parent.name in ('shard0','shard1','shard2','shard3','beam','opus47','muse_nvfp4','legacy_bench','review_bench','review_bench_20261018','opus47_full_20261018','opus47_review_20261020','strict_four_models_20261008'):
                (parent/'state').mkdir(exist_ok=True)
    (ROOT/'MATERIALIZATION.json').write_text(json.dumps({'workspace':str(workspace),'changed_execution_sources':changes},indent=2)+'\n')
    if args.install:
        subprocess.run([sys.executable,'-m','pip','install','-r',str(ROOT/'requirements.txt'),
            '-c',str(ROOT/'constraints.txt')],check=True)
        subprocess.run([sys.executable,'-m','pip','install','-e',str(workspace/'AgentCompass'),
            '-c',str(ROOT/'constraints.txt')],check=True)
        subprocess.run([sys.executable,'-m','pip','install','--no-deps','-e',
            str(workspace/'bench/code-review-eval/data/repos/swe-review/SWE-bench')],check=True)
        # The local installed Harbor source is the authoritative evaluated copy.
        import harbor
        shutil.copytree(workspace/'vendor/harbor',Path(harbor.__file__).parent,dirs_exist_ok=True)
    print(json.dumps({'verified_source_files':len(files),'relocated_execution_files':len(changes),'task_data_modified':False}))


if __name__=='__main__':main()
