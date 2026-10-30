"""Build a clean source delivery without runtime state or credentials."""
import argparse
import hashlib
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent
DIRECTORIES = {'.claude', 'agents', 'auth', 'storage', 'scripts', 'constraints', 'core', 'docs', 'examples',
               'knowledge', 'memory', 'research', 'swarm', 'validation', 'web'}
ROOT_FILES = {'.gitignore', '.env.example', 'alembic.ini', 'README.md', 'config.py', 'demo_basic.py', 'main.py',
              'requirements.txt', 'requirements.verified.txt', 'requirements.web.txt',
              'run_web.py', 'runtime_paths.py', 'setup.py', 'start.ps1', 'start_web.ps1',
              'verify_mem0.py', 'verify_runtime.py', 'package_project.py', 'web-ui-desktop.png',
              'run_kb_demo.py', 'requirements.kb.txt', 'AGENTS.md', '.env.example'}
PATTERNS = [rb'sk-(?:proj-|ws-)?[A-Za-z0-9_.-]{16,}', rb'm0-[A-Za-z0-9]{16,}',
            rb'gh[pousr]_[A-Za-z0-9]{20,}', rb'AKIA[0-9A-Z]{16}',
            rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----']


def check_credentials(name, data):
    if name.endswith('.docx'):
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as doc:
            texts = []
            for entry in doc.namelist():
                if entry.endswith('.xml'):
                    tree = ElementTree.fromstring(doc.read(entry))
                    texts.append(''.join(tree.itertext()))
            data = '\n'.join(texts).encode('utf-8')
    if any(re.search(pattern, data) for pattern in PATTERNS):
        raise ValueError(f'Possible credential in {name}; refusing to package')


def source_files():
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(ROOT)
        parts = relative.parts
        if any(part in {'__pycache__', '.git', '.pytest_cache', 'node_modules',
                        'session_summaries', 'agent_identities', '.local'} for part in parts):
            continue
        if parts[:2] == ('memory', 'agents'):
            continue
        if path.suffix in {'.pyc', '.log'} or path.name.startswith('verification_'):
            continue
        if len(parts) == 1:
            if path.name not in ROOT_FILES:
                continue
        elif parts[0] not in DIRECTORIES:
            continue
        if path.suffix == '.db' and relative.as_posix() != 'knowledge/data/milvus_lite.db':
            continue
        yield relative.as_posix(), path.read_bytes()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document', type=Path, required=True,
                        help='Word code walkthrough to include, without modifying the original')
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'delivery')
    parser.add_argument('--stamp', default=date.today().strftime('%Y%m%d'))
    args = parser.parse_args()
    if not re.fullmatch(r'\d{8}', args.stamp):
        parser.error('--stamp must be YYYYMMDD')
    items = dict(source_files())
    items['docs/医疗助手代码解读.docx'] = args.document.read_bytes()
    notes = '''# MediX 交付包说明

本包为可运行源码交付，不含依赖环境、模型权重或 API Key。解压后进入 medix-agent-swarm 目录。

## 新电脑启动（Windows / Python 3.12）

```powershell
py -3.12 -m venv ..\\.medix-venv
..\\.medix-venv\\Scripts\\python.exe -m pip install -r requirements.web.txt
.\\start_web.ps1
```

按隐藏输入提示提供模型 Key，再打开 http://127.0.0.1:8765/ 。Mem0 可选，使用 `start_web.ps1 -EnableMem0` 并手动开启页面开关。

- [项目说明与后续功能优先级](README.md)
- [运行架构与排障](docs/RUNTIME.md)
- [测试方法与范围](docs/TESTING.md)
- [医疗助手代码解读 Word 文档](docs/医疗助手代码解读.docx)

README 中“当前 Windows 环境”的绝对路径是原开发机路径；在其他电脑应改为实际解压目录。默认外部配置文件不存在时，可以直接使用启动脚本隐藏输入；自定义配置路径用 MEDIX_CONFIG_PATH 指定。

保留 10 份项目原始医学 TXT 和仅含附带知识资料的旧向量源库，启动时迁移已有 180 条索引。文档来源和医学内容尚未审核。本包无模型训练/微调模块，无历史会话保存功能；后续建议不代表已经实现。

Word 文件按用户提供的原件打包，未更新其内部内容；若与代码或新版 README 有出入，以当前源码与 README 为准。

未包含：任何 API Key、外部 config 文件、虚拟环境、模型缓存、运行日志、用户会话摘要、浏览器聊天记录、开发机测试输出。网页截图仅为界面预览，demo-report.png 为虚构测试记录。

PACKAGE-MANIFEST.json 列出本包各文件的 SHA-256。ZIP 同目录的 .sha256 用于校验整个压缩包。
'''
    items['DELIVERY.md'] = notes.encode('utf-8')
    for name, data in items.items():
        check_credentials(name, data)
    manifest = {'package': 'medix-agent-swarm', 'date': args.stamp,
                'credential_pattern_scan': 'passed',
                'files': [{'path': name, 'bytes': len(data),
                           'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in sorted(items.items())]}
    items['PACKAGE-MANIFEST.json'] = json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8')
    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / f'medix-agent-swarm-{args.stamp}.zip'
    if archive.exists():
        raise FileExistsError(f'Refusing to overwrite existing delivery: {archive}')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipped:
        for name, data in sorted(items.items()):
            zipped.writestr('medix-agent-swarm/' + name, data)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        assert len(zipped.namelist()) == len(items)
        for entry in manifest['files']:
            assert hashlib.sha256(zipped.read('medix-agent-swarm/' + entry['path'])).hexdigest() == entry['sha256']
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'files': len(items), 'bytes': archive.stat().st_size,
                      'sha256': digest, 'credential_pattern_scan': 'passed'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
