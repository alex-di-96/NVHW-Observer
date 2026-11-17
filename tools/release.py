#!/usr/bin/env python3
"""Check and export an explicitly reviewed source set. No network or publishing."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

ROOT=Path(__file__).resolve().parents[1]
LIST='public-files.txt'
GENERATED={'SHA256SUMS'}
IGNORED_DIRS={'.git','__pycache__','.venv','build','dist','htmlcov'}
SENSITIVE=[
    ('private-key',re.compile(r'-----BEGIN (?:OPENSSH|RSA|EC|DSA|ENCRYPTED) PRIVATE KEY-----')),
    ('github-token',re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b')),
    ('home-path',re.compile(r'/(?:home|Users)/[^/\s]+/')),
    ('private-ip',re.compile(r'\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b')),
    ('credential-assignment',re.compile(r'(?im)^\s*(?:password|passwd|access_token|auth_token)\s*[:=]\s*[\x22\x27]?[^\s\x22\x27]{4,}')),
]


def sha(data):return hashlib.sha256(data).hexdigest()


def names(root):
    rows=[s.strip() for s in (root/LIST).read_text().splitlines() if s.strip() and not s.startswith('#')]
    if rows!=sorted(set(rows)):raise ValueError('public-files.txt must be unique and sorted')
    for name in rows:
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or str(p)!=name:
            raise ValueError('invalid public path: '+name)
        if '.git' in p.parts or p.suffix.lower() in {'.efi','.rom','.bin','.deb','.pem','.key','.log'}:
            raise ValueError('excluded asset type: '+name)
    return rows


def ignored(path):
    return any(p in IGNORED_DIRS or p.endswith('.egg-info') or p.startswith(('build-','qemu-results'))
               for p in path.parts) or path.suffix in {'.pyc','.pyo'}


def check(root=ROOT):
    root=root.resolve();listed=names(root);data={};issues=[]
    for name in listed:
        path=root/name
        if any((root/Path(*PurePosixPath(name).parts[:n])).is_symlink()
               for n in range(1,len(PurePosixPath(name).parts)+1)):
            issues.append(name+': symlink');continue
        if not path.is_file():issues.append(name+': missing file');continue
        raw=path.read_bytes();data[name]=raw
        try:text=raw.decode('utf-8')
        except UnicodeDecodeError:issues.append(name+': non-text asset');continue
        if '\0' in text:issues.append(name+': binary content')
        for label,pattern in SENSITIVE:
            if pattern.search(text):issues.append(name+': '+label)  # never print matched secrets
        if path.suffix=='.md':
            for dest in re.findall(r'(?<!!)\[[^\]]*\]\(([^\s)]+)\)',text):
                dest=dest.split('#',1)[0]
                if not dest or re.match(r'[a-zA-Z]+:',dest):continue
                resolved=(path.parent/dest).resolve()
                if not resolved.is_relative_to(root) or str(resolved.relative_to(root)) not in listed:
                    issues.append(name+': missing/nonpublic link '+dest)
    for path in root.rglob('*'):
        rel=path.relative_to(root)
        if ignored(rel) or str(rel) in GENERATED:continue
        if (path.is_file() or path.is_symlink()) and str(rel) not in listed:
            issues.append(str(rel)+': unreviewed file')
    if issues:raise ValueError('\n'.join(issues))
    hashes={name:sha(raw) for name,raw in data.items()}
    sums=''.join(f'{digest}  {name}\n' for name,digest in hashes.items())
    if (root/'SHA256SUMS').exists() and (root/'SHA256SUMS').read_text()!=sums:
        raise ValueError('export SHA256SUMS mismatch')
    return data,sums


def export(root,output,archive=None):
    data,sums=check(root)
    if output.exists():raise ValueError('preserve existing export')
    if output.resolve().is_relative_to(root.resolve()):raise ValueError('export must be outside source directory')
    if archive and (archive.exists() or archive.resolve().is_relative_to(output.resolve())):
        raise ValueError('archive must be a new file outside export')
    output.mkdir(parents=True)
    for name,raw in data.items():
        dest=output/name;dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as f:f.write(raw)
    (output/'SHA256SUMS').write_text(sums)
    if archive:
        archive.parent.mkdir(parents=True,exist_ok=True)
        with archive.open('xb') as stream, gzip.GzipFile(filename='',mode='wb',fileobj=stream,mtime=0) as gz:
            with tarfile.open(fileobj=gz,mode='w',format=tarfile.PAX_FORMAT) as tar:
                for name,raw in sorted({**data,'SHA256SUMS':sums.encode()}.items()):
                    info=tarfile.TarInfo('NVHW-observer/'+name)
                    info.size=len(raw);info.mode=0o644;info.mtime=0;info.uid=info.gid=0
                    tar.addfile(info,io.BytesIO(raw))
    return {'files':len(data),'source_set_sha256':sha(sums.encode()),
            'archive_sha256':sha(archive.read_bytes()) if archive else None,
            'published':False,'history_included':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('check','export'))
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path);parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    try:
        if args.command=='check':
            data,sums=check(args.root)
            result={'files':len(data),'source_set_sha256':sha(sums.encode()),'check':'PASS'}
        else:
            if args.out is None:parser.error('export requires --out')
            result=export(args.root,args.out,args.archive)
    except (OSError,ValueError) as exc:parser.exit(2,str(exc)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
