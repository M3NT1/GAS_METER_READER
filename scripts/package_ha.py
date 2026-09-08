"""Create a zip that can be copied to a Home Assistant config directory."""

from argparse import ArgumentParser
from pathlib import Path
import zipfile


def main() -> None:
    parser = ArgumentParser(description='Package the Gas Photo Home Assistant integration')
    parser.add_argument(
        '--output',
        type=Path,
        default=Path('dist/gas_photo-custom-component.zip'),
        help='Output zip path (default: dist/gas_photo-custom-component.zip)',
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    source = root / 'custom_components' / 'gas_photo'
    if not source.is_dir():
        raise SystemExit(f'Missing integration directory: {source}')

    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path for path in source.rglob('*')
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc'
    )
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, Path('custom_components') / 'gas_photo' / path.relative_to(source))
    print(f'Created {output} ({len(files)} files)')


if __name__ == '__main__':
    main()
