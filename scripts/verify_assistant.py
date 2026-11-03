"""Reproducible cloud-free M6 acceptance; only new disposable F-drive output.

Use --source for an existing curated snapshot, or --snapshot-files for an explicit
JSON list of changed files to overlay on git archive HEAD. Never copy the worktree.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
from release_assistant import validate_test_project


def snapshot(root, destination, files):
    raw = subprocess.run(['git', 'archive', 'HEAD'], cwd=root, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        archive.extractall(destination, filter='data')
    hashes = {}
    for name in files:
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or any(p in ('.workbuddy', '.agents', '.vscode', '.git') for p in path.parts) or '.env' in path.name and not path.name.endswith('.example'):
            raise ValueError('Unsafe snapshot overlay file')
        source = (root / name).resolve()
        if not source.is_relative_to(root) or not source.is_file(): raise ValueError('Invalid snapshot file')
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        hashes[name] = hashlib.sha256(source.read_bytes()).hexdigest()
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--source', type=Path)
    group.add_argument('--snapshot-files', type=Path)
    parser.add_argument('--project', type=validate_test_project, default='my-campus-ai-m6-verify')
    parser.add_argument('--docker', default='F:/my-campus-dev/docker/app/resources/bin/docker.exe')
    parser.add_argument('--node', default='E:/Program Files/nodejs/node.exe')
    parser.add_argument('--npm', default='E:/Program Files/nodejs/npm.cmd')
    parser.add_argument('--playwright', help='Optional existing module; default installs the independent browser-test lock')
    parser.add_argument('--browser', required=True)
    parser.add_argument('--ui-port', type=int, default=15186)
    parser.add_argument('--proxy-port', type=int, default=18765)
    parser.add_argument('--test-image', default='my-campus-ai-m2-test-tests:latest')
    parser.add_argument('--old-image', default='my-campus-backend:m4-verified')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.drive.upper() != 'F:' or output.exists(): parser.error('New F-drive output directory required')
    output.mkdir(parents=True)
    root = Path(__file__).resolve().parents[1]
    source = args.source.resolve() if args.source else output/'source'
    report = {'passed': False, 'cloud_calls': 0, 'project': args.project, 'stages': [], 'images': {}, 'tests': {}}
    owned = []
    def run(name, command, cwd=source, env=None, timeout=900):
        try:
            result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as error:
            report['stages'].append({'name': name, 'error': type(error).__name__})
            raise
        (output/(name+'.log')).write_bytes(result.stdout + result.stderr)
        report['stages'].append({'name': name, 'exit': result.returncode})
        if result.returncode: raise RuntimeError('Acceptance stage failed: '+name)
        return result.stdout
    try:
        report['commit'] = run('commit', ['git','rev-parse','HEAD'], cwd=root).decode().strip()
        if not args.source:
            report['overlay_sha256'] = snapshot(root, source, json.loads(args.snapshot_files.read_text(encoding='utf-8')) if args.snapshot_files else [])
        else:
            if source.drive.upper() != 'F:': raise ValueError('Curated source must be on F drive')
            manifest = source/'snapshot-manifest.json'
            if not manifest.is_file(): raise ValueError('Curated source requires snapshot-manifest.json provenance')
            report['source_manifest'] = json.loads(manifest.read_text(encoding='utf-8'))
            report['commit'] = report['source_manifest']['commit']
            if not re.fullmatch('[0-9a-f]{40}', report['commit']): raise ValueError('Invalid snapshot source commit')
        (output/'snapshot-manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        for name, image in [('test',args.test_image), ('rollback',args.old_image)]:
            report['images'][name] = run('image-'+name,[args.docker,'image','inspect','--format','{{.Id}}',image]).decode().strip()
        playwright = str(Path(args.playwright).resolve() if args.playwright else source/'scripts/browser-tests/node_modules/playwright')
        overlay = output/'tests-compose.json'
        overlay.write_text(json.dumps({'services': {'tests': {'image':args.test_image, 'volumes':[f'{(source/"backend"/name).as_posix()}:/app/{name}:ro' for name in ('app','tests','migrations')]}}}),encoding='utf-8')
        test = [args.docker,'compose','-p',args.project,'-f',str(source/'compose.assistant-test.yaml'),'-f',str(overlay)]
        if run('test-empty',test+['ps','-a','-q']).strip(): raise ValueError('Refuse existing test project')
        owned.append(test)
        run('test-start',test+['up','-d','--wait','test-mysql','checkpoint-mysql','test-redis'])
        result=run('backend',test+['run','--rm','--no-deps','tests','python','-B','-m','pytest','-q','-ra','-p','no:cacheprovider','tests'])
        report['tests']['backend'] = {key: int((re.search(rb'\b([0-9]+) '+key.encode()+rb'\b', result) or [b'',b'0'])[1]) for key in ('passed','failed','skipped')}
        if re.search(rb'\b[1-9][0-9]* skipped\b',result): raise RuntimeError('Required backend integration tests skipped')
        run('script-tests',[sys.executable,'-B','-m','unittest','discover','-s','scripts/tests'])
        run('health-tests',[sys.executable,'-B','-m','unittest','discover','-s','scripts','-p','test_check_assistant_operations.py'])
        if not args.playwright:
            run('browser-dependencies',[args.npm,'ci','--offline','--ignore-scripts','--cache','F:/my-campus-dev/cache/npm'],cwd=source/'scripts/browser-tests')
        if json.loads((Path(playwright)/'package.json').read_text(encoding='utf-8'))['version'] != '1.62.1': raise ValueError('Browser dependency must match locked 1.62.1')
        run('frontend-dependencies',[args.npm,'ci','--offline','--ignore-scripts','--cache','F:/my-campus-dev/cache/npm'],cwd=source/'frontend')
        run('type-check',[args.npm,'run','type-check'],cwd=source/'frontend')
        run('build',[args.npm,'run','build'],cwd=source/'frontend')
        run('sse',[args.node,'--test','frontend/tests/assistant-events.test.mjs'])
        run('ui',[args.node,'scripts/verify_assistant_ui.mjs','--dist',str(source/'frontend/dist'),'--output',str(output/'ui'),'--playwright',playwright,'--browser',args.browser,'--port',str(args.ui_port)])
        for kind, context, target in [('backend','backend','runtime'), ('assistant','backend','assistant'), ('frontend','frontend',None)]:
            tag = f'my-campus-{kind}:{args.project}'
            command = [args.docker,'build','--label',f'org.opencontainers.image.revision={report["commit"]}','-t',tag]
            if target:
                command += ['--target',target]
            run('build-'+kind,command+[str(source/context)])
            report['images'][kind] = run('built-image-'+kind,[args.docker,'image','inspect','--format','{{.Id}}',tag]).decode().strip()
            run('check-'+kind,[args.docker,'run','--rm','--network','none',tag,'python','-m','pip','check'] if target else
                [args.docker,'run','--rm','--network','none',tag,'nginx','-v'])
        e2e_project = args.project.replace('-verify','-e2e')
        if e2e_project == args.project: raise ValueError('Unified runner requires verify project prefix')
        env = dict(os.environ, E2E_ARTIFACT_DIR=(output/'e2e').as_posix(), E2E_DIST_DIR=(source/'frontend/dist').as_posix(), E2E_PROXY_PORT=str(args.proxy_port), E2E_TEST_IMAGE=args.test_image)
        (output/'e2e').mkdir()
        e2e = [args.docker,'compose','-p',e2e_project,'-f',str(source/'compose.assistant-test.yaml'),'-f',str(source/'compose.assistant-e2e.yaml')]
        if run('e2e-empty',e2e+['ps','-a','-q'],env=env).strip(): raise ValueError('Refuse existing e2e project')
        owned.append((e2e,env))
        run('e2e-start',e2e+['up','-d','--wait','--no-build','test-mysql','checkpoint-mysql','test-redis','api','e2e-proxy'],env=env)
        report['images']['e2e_container'] = run('e2e-image',[args.docker,'container','inspect','--format','{{.Image}}',e2e_project+'-api-1']).decode().strip()
        origin = f'http://127.0.0.1:{args.proxy_port}'
        run('e2e',[args.node,'scripts/verify_assistant_e2e.mjs','--artifacts',str(output/'e2e'),'--playwright',playwright,'--browser',args.browser,'--origin',origin])
        run('access-e2e',[args.node,'scripts/verify_assistant_access_e2e.mjs','--artifacts',str(output/'e2e'),'--origin',origin])
        run('operations',[args.node,'scripts/verify_assistant_operations.mjs','--artifacts',str(output/'e2e'),'--project',e2e_project,'--docker',args.docker,'--origin',origin])
        run('release',[sys.executable,'scripts/rehearse_assistant_release.py','--source',str(source),'--docker',args.docker,'--output',str(output/'release'),'--old-image',args.old_image,'--test-image',args.test_image])
        run('release-compose',[sys.executable,'scripts/rehearse_assistant_compose.py','--output',str(output/'release-compose'),'--docker',args.docker,'--image-project',args.project])
        report['passed'] = True
    except Exception as error:
        report['failure'] = type(error).__name__
    finally:
        for index, entry in enumerate(reversed(owned)):
            command, env = entry if isinstance(entry,tuple) else (entry,None)
            try: run('cleanup-'+str(index),command+['down'],env=env)
            except Exception: report['passed']=False; report['cleanup_failed']=True
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'report':str(output/'report.json')}))
    return 0 if report['passed'] else 1

if __name__ == '__main__': raise SystemExit(main())
