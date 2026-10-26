"""Produce a source download without credentials, caches, or recursive archives."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
root=Path(__file__).resolve().parents[1]
target=root/'dist/downloads/fret-source.zip'
target.parent.mkdir(parents=True,exist_ok=True)
with ZipFile(target,'w',ZIP_DEFLATED) as archive:
    for name in ['README.md','requirements.txt','.env.example','.gitignore']:
        archive.write(root/name,'fret/'+name)
    for directory in ['dist','backend','scripts','tests']:
        for path in sorted((root/directory).rglob('*')):
            if path.is_file() and not any(s in path.parts for s in ['__pycache__','downloads']):
                archive.write(path,'fret/'+str(path.relative_to(root)))
print(target)
