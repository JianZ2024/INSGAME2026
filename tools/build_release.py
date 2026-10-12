"""Build an allowlisted GitHub source archive without local classrooms or secrets."""
import hashlib
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    '.gitignore', '.gitattributes', '.github/workflows/checks.yml', '.vscode/launch.json',
    'README.md', 'RULES.md', 'LICENSE', 'requirements.txt', 'app.py', 'engine.py', 'store.py',
    'static/index.html', 'static/app.js', 'static/dashboard.js', 'static/investment.js',
    'static/market.js', 'static/style.css', 'static/favicon.svg',
    'tests/test_game.py', 'tests/test_investments.py', 'tests/test_regions.py',
    'tests/test_dashboard.cjs', 'tests/test_market.cjs',
    'examples/demo_round.py', 'docs/EXAMPLE_RESULTS.md', 'docs/GITHUB_UPLOAD.md',
    'tools/build_release.py',
)


def main():
    missing = [name for name in FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit('Missing release files: ' + ', '.join(missing))
    # Resolve each source before reading it, so links cannot pull in unrelated files.
    for name in FILES:
        path = ROOT / name
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise SystemExit('Release source is outside the project: ' + name)
    output = ROOT / 'releases'
    output.mkdir(exist_ok=True)
    archive = output / 'INSGAME2026-github.zip'
    manifest = []
    with ZipFile(archive, 'w', compression=ZIP_DEFLATED) as release:
        for name in FILES:
            data = (ROOT / name).read_bytes()
            release.writestr('INSGAME2026/' + name, data)
            manifest.append(hashlib.sha256(data).hexdigest() + '  ' + name)
        release.writestr('INSGAME2026/MANIFEST.sha256', '\n'.join(manifest) + '\n')
    with ZipFile(archive) as release:
        if release.testzip() is not None:
            raise SystemExit('Archive verification failed.')
    print(f'Created {archive.name}: {len(FILES)} source files plus MANIFEST.sha256.')
    print(f'Location: {archive}')
    print('No runtime databases, credentials, local handoff notes, or old screenshots included.')


if __name__ == '__main__':
    main()
