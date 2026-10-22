#!/usr/bin/env python3
"""Fetch fixed HF image archives and verify loaded image IDs and layers."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from huggingface_hub import hf_hub_download

ROOT=Path(__file__).resolve().parent


def inspect_image(row):
    p=subprocess.run(['docker','image','inspect',row['tag']],capture_output=True,text=True)
    if p.returncode:return False
    value=json.loads(p.stdout)[0]
    return value['Id']==row['config_digest'] and value['RootFS']['Layers']==row['rootfs_diff_ids']


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--task',action='append',help='Repeat to select task names; omitted means all 89')
    p.add_argument('--download',action='store_true');p.add_argument('--load',action='store_true')
    p.add_argument('--directory',type=Path,default=ROOT/'image_archives')
    args=p.parse_args();lock=json.loads((ROOT/'TB21_IMAGE_LOCK.json').read_text())
    rows=[r for r in lock['images'] if not args.task or r['task'] in args.task]
    assert rows and (not args.task or set(args.task)=={r['task'] for r in rows})
    assert not args.load or args.download,'Use --download --load together'
    print(json.dumps({'images':len(rows),'archive_GB':sum(r['archive_bytes'] for r in rows)/1e9,
        'repository':lock['repo_id'],'revision':lock['revision'],'download':args.download}),flush=True)
    if not args.download:return
    for row in rows:
        if args.load and inspect_image(row):
            print('verified existing image',row['task'],flush=True);continue
        path=Path(hf_hub_download(lock['repo_id'],row['hub_path'],revision=lock['revision'],local_dir=args.directory))
        assert path.stat().st_size==row['archive_bytes'],row['task']
        if row.get('archive_sha256'):
            with path.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==row['archive_sha256'],row['task']
        if args.load:
            subprocess.run(['docker','load','-i',str(path)],check=True)
            assert inspect_image(row),'Loaded image identity mismatch: '+row['task']
        print('verified archive',row['task'],flush=True)


if __name__=='__main__':main()
