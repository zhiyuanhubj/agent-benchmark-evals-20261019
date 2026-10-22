#!/usr/bin/env python3
"""Build a private, portable snapshot of the actual local evaluation sources."""
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone

BASE = Path('/fsx/home/zhiyuan')
REPO = BASE/'agent-benchmark-evals-20261019'
OUT = BASE/'.private/hf_benchmark_repro_20261022/upload'
MUSE = BASE/'.private/muse_spark_open_20261016'
BEAM = BASE/'.private/beam_20261018'
BF16 = BASE/'.private/muse_bf16_20261018'
EXACT = BEAM/'tb_v1_exact_images_20261019'
STRICT = BASE/'bench/strict_four_models_20261008'
CR = BASE/'bench/code-review-eval/data/repos'
FILES = {}
REDACTIONS = []
SKIP = {'.git','__pycache__','.venv','node_modules','.cache','results'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def add(path, destination=None):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return
    dest = destination or str(path.relative_to(BASE))
    if dest in FILES:
        assert FILES[dest] == path
    FILES[dest] = path


def tree(root, destination=None):
    root = Path(root)
    for directory, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in names:
            if name.endswith(('.pyc','.key','.lock','.sqlite3')) or name in ('.env','token','stored_tokens'):
                continue
            path = Path(directory)/name
            add(path, str(Path(destination)/path.relative_to(root)) if destination else None)


def tracked(root, destination=None):
    root = Path(root)
    paths = subprocess.check_output(['git','-C',str(root),'ls-files','-z'],text=True).split('\0')
    for name in paths:
        if not name or any(part in (SKIP-{'results'}) for part in Path(name).parts):
            continue
        add(root/name, str(Path(destination)/name) if destination else None)


def source_folder(root):
    root = Path(root)
    for path in root.glob('*.py'):
        add(path)
    for folder in ('vendor','protocol_reference'):
        if (root/folder).is_dir():
            tree(root/folder)


def clean_json(value):
    if isinstance(value,list):
        return [clean_json(x) for x in value]
    if isinstance(value,dict):
        result={}
        for key,item in value.items():
            if isinstance(item,str) and any(s in key.upper() for s in ('API_KEY','ACCESS_TOKEN','AUTHORIZATION')):
                if item not in ('','EMPTY','dummy-key','dummy','DUMMY') and not item.startswith('${'):
                    item='${MODEL_API_KEY}';REDACTIONS.append(key)
            result[key]=clean_json(item)
        return result
    return value


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'workspace.tar.zst').exists(), 'Use a new staging snapshot rather than overwrite a released bundle'
    tracked(BASE/'AgentCompass')
    tracked(BASE/'AgentCompass-official-baseline')
    pro_data=BASE/'AgentCompass-official-baseline/data/swe_bench_pro_verified/swebench_pro_verified.jsonl'
    assert len({json.loads(line)['instance_id'] for line in pro_data.read_text().splitlines() if line.strip()})==731
    add(pro_data)  # This downloaded input is intentionally ignored by upstream Git.
    tracked(CR/'swe-review')
    # The official verifier repository may be a populated Git submodule.
    if (CR/'swe-review/SWE-bench/swebench').is_dir():
        tracked(CR/'swe-review/SWE-bench')
    tracked(CR/'swrbench')
    add(CR/'swrbench/data/swr_datasets_d5c5.jsonl')
    tree(STRICT/'sources/terminal-bench-2-1')
    source_folder(STRICT)
    tree(STRICT/'sources/swe-pro/v2/tooling')
    common=BASE/'bench/tb21_v1_four_models_20261012'
    source_folder(common)
    tree(common/'protocol_reference')
    deep=[]
    for n in range(4):
        root=MUSE/f'shard{n}'
        source_folder(root)
        for p in (root/'configs').glob('*.json'):add(p)
        config=json.loads((root/'configs/deep.json').read_text())['config']
        deep.extend(t['path'] for t in config['tasks'])
    assert len(deep)==len(set(deep))==113
    for task in deep:tree(task)
    for root in (EXACT/'beam',EXACT/'opus47',EXACT/'muse_nvfp4',
                 BEAM/'legacy_bench_20261018/remaining_pro',
                 BEAM/'legacy_bench_20261018/remaining_deep',
                 BF16/'legacy_bench',BASE/'bench/opus47_full_20261018'):
        source_folder(root)
        for p in root.glob('*command*.json'):add(p)
        if (root/'configs').is_dir():
            for p in (root/'configs').glob('*.json'):add(p)
    for root in (MUSE/'review_bench_20261018',BEAM/'review_bench',BF16/'review_bench'):
        source_folder(root)
        if (root/'configs').is_dir():
            for p in (root/'configs').glob('*.json'):add(p)
    opus_review=BASE/'.private/opus47_review_20261020'
    source_folder(opus_review)
    for p in (opus_review/'configs').glob('*.json'):add(p)
    tree(BASE/'bench/mswea-wheelhouse')
    tree(BASE/'.private/nemotron35super/runs/opus48_mix3_20261014/early9_full_validation_20261017/state/client-dependency-repair-wheels')
    review=MUSE/'review_bench_20261018/swe_review'
    splits={}
    for split in ('glm5_500','qwen3_coder_30b_500','qwen3_30b_instruct2507_500'):
        tree(review/split/'tasks')
        splits[split]=len(list((review/split/'tasks').glob('*/task.toml')))
    assert list(splits.values())==[500,462,422],splits
    # Preserve the actual installed Harbor source, including local edits, rather
    # than assuming that a fresh upstream installation is byte-identical.
    import harbor
    tree(Path(harbor.__file__).parent,'vendor/harbor')
    distribution=importlib.metadata.distribution('harbor')
    for item in distribution.files or []:
        if 'licenses' in item.parts:
            add(distribution.locate_file(item),'vendor/harbor-license/'+item.name)
    # Include a committed result/protocol snapshot, not live credentials or the
    # mutable original output trees. Historic full I/O stays in GitHub Releases.
    ref=OUT/'reference'
    ref.mkdir(exist_ok=True)
    subprocess.run(['git','archive','--format=tar','-o',str(ref/'evaluation_snapshot.tar'),'HEAD'],cwd=REPO,check=True)
    process=subprocess.run(['zstd','-q','-T2','-3','--rm',str(ref/'evaluation_snapshot.tar')],check=True)
    sources={}
    archive=OUT/'workspace.tar.zst'
    process=subprocess.Popen(['zstd','-q','-T2','-3','-o',str(archive)],stdin=subprocess.PIPE)
    with tarfile.open(fileobj=process.stdin,mode='w|') as tar:
        for dest,path in sorted(FILES.items()):
            data=path.read_bytes()
            original=sha(data)
            task_data=('/sources/terminal-bench-2-1/' in str(path) or '/sources/deep-swe/tasks/' in str(path)
                       or ('/swe_review/' in str(path) and '/tasks/' in str(path)))
            if not task_data and path.suffix=='.json' and any(x in path.parts for x in ('configs','protocol_reference')):
                try:data=(json.dumps(clean_json(json.loads(data)),indent=2)+'\n').encode()
                except (ValueError,UnicodeDecodeError):pass
            # A conservative literal-token check; never print candidate values.
            # sanitize-git-repo deliberately contains public synthetic tokens
            # in its tests. Preserve benchmark fixtures byte-for-byte.
            fixture=(STRICT/'sources/terminal-bench-2-1/sanitize-git-repo') in path.parents
            if not fixture and path.suffix in ('.py','.sh','.json','.toml','.yaml','.yml'):
                assert not re.search(rb'\b(?:hf_[A-Za-z0-9]{24,}|sk-(?:proj-|ant-)?[A-Za-z0-9_-]{28,})',data), f'Credential-shaped literal in {dest}; review privately'
            info=tarfile.TarInfo('workspace/'+dest)
            info.size=len(data);info.mode=0o755 if os.access(path,os.X_OK) else 0o644
            tar.addfile(info,io.BytesIO(data))
            sources[dest]={'bytes':len(data),'sha256':sha(data),'original_sha256':original}
    process.stdin.close();assert process.wait()==0
    provenance={
        'created_utc':datetime.now(timezone.utc).isoformat(),
        'benchmark_snapshot_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),
        'agentcompass_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=BASE/'AgentCompass',text=True).strip(),
        'agentcompass_dirty_files':subprocess.check_output(['git','diff','--name-only'],cwd=BASE/'AgentCompass',text=True).splitlines(),
        'task_counts':{'tb21':89,'pro':731,'deepswe':113,'swrbench':1000,'swe_review':splits},
        'deepswe_task_paths':deep,'redacted_config_fields':sorted(set(REDACTIONS)),
        'archive_bytes':archive.stat().st_size,
        'archive_sha256':hashlib.file_digest(archive.open('rb'),'sha256').hexdigest(),
        'files':sources,
        'scope':'Actual working-tree source and fixed task inputs; no model weights, API credentials, GPU allocations, active controllers, or bulk historical trajectory archives.'}
    (OUT/'WORKSPACE_MANIFEST.json').write_text(json.dumps(provenance,indent=2)+'\n')
    versions={d.metadata['Name']:d.version for d in importlib.metadata.distributions() if d.metadata.get('Name')}
    (OUT/'INSTALLED_VERSIONS.json').write_text(json.dumps(versions,indent=2,sort_keys=True)+'\n')
    # The broad version snapshot is evidence; this small operational lock avoids
    # pulling unrelated GPU/model-training packages into an evaluation host.
    keep=['harbor','mini-swe-agent','openai','anthropic','litellm','httpx','huggingface-hub','datasets',
          'pydantic','fastapi','uvicorn','pandas','numpy','aiofiles','aiohttp','tenacity','jinja2',
          'python-dotenv','PyYAML','rich','toml','shortuuid']
    (OUT/'requirements.txt').write_text('\n'.join(f'{k}=={importlib.metadata.version(k)}' for k in keep)+'\n')
    (OUT/'AGENTCOMPASS_LOCAL.patch').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=BASE/'AgentCompass'))
    print(json.dumps({'files':len(sources),'bytes':provenance['archive_bytes'],'counts':provenance['task_counts']}),flush=True)


if __name__=='__main__':main()
