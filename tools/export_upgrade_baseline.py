"""Export the immutable public 0.7.0 source snapshot, never private installers."""
from io import BytesIO
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile

BASELINE='3959e3d4830e359b9c0f720d76bb7c58634591c5'
STAGE14='b394f4b1f23b8913d7def0ab6eaaa39cc96972b6'


def export(root,destination,revision=BASELINE):
    if revision not in {BASELINE,STAGE14}:raise ValueError('Only pinned public source baselines are supported')
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
    data=subprocess.check_output(['git','archive','--format=zip',revision],cwd=root)
    with ZipFile(BytesIO(data)) as archive:
        if any(Path(n).is_absolute() or '..' in Path(n).parts for n in archive.namelist()):raise ValueError('Unsafe source archive')
        archive.extractall(destination)
    (destination/'upgrade-baseline.json').write_text(json.dumps({'revision':revision,
        'archiveSha256':hashlib.sha256(data).hexdigest()}),encoding='utf-8')
    return revision


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination',type=Path)
    parser.add_argument('--revision',choices=[BASELINE,STAGE14],default=BASELINE)
    args=parser.parse_args()
    print(export(Path(__file__).resolve().parents[1],args.destination,args.revision))
