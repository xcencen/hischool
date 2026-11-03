"""Read-only release admission: verifies evidence and local immutable images.

This command emits a review plan only. It never runs Compose, migration or deploy.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

REVISION = '0007_assistant_access'
SERVICES = ('mysql', 'redis', 'api', 'worker', 'assistant-worker', 'campus-mcp', 'frontend')
MATERIALS = ('accounts', 'notice', 'outbound_fields', 'prices_quotas', 'retention', 'window', 'responsible', 'backup_restore', 'verification')
REQUIRED_STAGES = {'backend', 'script-tests', 'health-tests', 'type-check', 'build', 'sse', 'ui',
    'build-backend', 'build-assistant', 'build-frontend', 'check-backend', 'check-assistant', 'check-frontend',
    'e2e', 'access-e2e', 'operations', 'release', 'release-compose', 'cleanup-0', 'cleanup-1'}


def verification_report(data, base):
    report = json.loads((base/data['admission']['verification']['path']).read_text(encoding='utf-8'))
    counts = report.get('tests', {}).get('backend', {})
    stages = {item['name'] for item in report.get('stages', []) if item.get('exit') == 0}
    if (report.get('passed') is not True or report.get('commit') != data['commit']
            or report.get('cloud_calls') != 0 or counts.get('passed', 0) <= 0
            or counts.get('failed') != 0 or counts.get('skipped') != 0
            or not REQUIRED_STAGES.issubset(stages)
            or any(not report.get('images', {}).get(k) for k in ('backend', 'assistant', 'frontend', 'rollback'))):
        raise ValueError('Release verification must pass for this source and images without skips')
    return report


def validate_test_project(value):
    if not re.fullmatch(r'my-campus-ai-m6-(?:release|e2e|verify)(?:-[a-z0-9-]+)?', value):
        raise ValueError('A dedicated M6 release/e2e/verify test project is required')
    return value


def validate_image(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9./_:-]+@sha256:[0-9a-f]{64}', value):
        raise ValueError('Every image must use an immutable registry digest')
    return value


def validate_evidence(item, base):
    if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
        raise ValueError('Admission evidence requires path and sha256')
    path = (base / item['path']).resolve()
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
        raise ValueError('Admission evidence missing or hash differs')


def validate_manifest(data, base):
    if not isinstance(data.get('admission'), dict) or any(not data['admission'].get(k) for k in MATERIALS):
        raise ValueError('Missing release admission materials')
    if data.get('revision') != REVISION or not re.fullmatch('[0-9a-f]{40}', data.get('commit', '')):
        raise ValueError('Unverified release revision or commit')
    if data.get('assistant_enabled') is not False or data.get('allow_campus_data') is not False:
        raise ValueError('This release plan requires both switches closed')
    if set(data.get('images', {})) != set(SERVICES):
        raise ValueError('All release images are required')
    for image in data['images'].values(): validate_image(image)
    for material in MATERIALS: validate_evidence(data['admission'][material], base)
    verification_report(data, base)
    if data.get('config_template_version') != 'm6-closed-v1' or not re.fullmatch('[0-9a-f]{40}', data.get('rollback_commit', '')):
        raise ValueError('Release configuration template and rollback source are required')
    if set(data.get('rollback_images', {})) != set(SERVICES):
        raise ValueError('All rollback images are required')
    for image in data['rollback_images'].values(): validate_image(image)
    valid_until = datetime.fromisoformat(data.get('valid_until', '').replace('Z', '+00:00'))
    if valid_until.tzinfo is None or valid_until <= datetime.now(timezone.utc):
        raise ValueError('Release admission has expired')
    return data


def verify_images(data, docker, report):
    for service, image in data['images'].items():
        result = subprocess.run([docker, 'image', 'inspect', image], capture_output=True, timeout=20)
        if result.returncode: raise ValueError('Release image is not locally verified: ' + service)
        inspected = json.loads(result.stdout)[0]
        if image not in inspected.get('RepoDigests', []):
            raise ValueError('Release image digest differs: ' + service)
        if service not in ('mysql', 'redis') and inspected.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != data['commit']:
            raise ValueError('Release image source commit differs: ' + service)
        kind = {'api':'backend','worker':'backend','assistant-worker':'assistant','campus-mcp':'assistant','frontend':'frontend'}.get(service)
        if kind and inspected.get('Id') != report['images'][kind]:
            raise ValueError('Release image differs from verification: ' + service)
    for service, image in data['rollback_images'].items():
        result = subprocess.run([docker, 'image', 'inspect', image], capture_output=True, timeout=20)
        if result.returncode or image not in json.loads(result.stdout)[0].get('RepoDigests', []):
            raise ValueError('Rollback image digest is not locally verified')
        inspected = json.loads(result.stdout)[0]
        if service in ('api', 'worker') and inspected.get('Id') != report['images']['rollback']:
            raise ValueError('Rollback image differs from rehearsal')
        revision = inspected.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision')
        if service not in ('mysql','redis') and revision and revision != data['rollback_commit']:
            raise ValueError('Rollback image source differs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--docker', default='F:/my-campus-dev/docker/app/resources/bin/docker.exe')
    args = parser.parse_args()
    try:
        data = validate_manifest(json.loads(args.manifest.read_text(encoding='utf-8')), args.manifest.resolve().parent)
        verify_images(data, args.docker, verification_report(data, args.manifest.resolve().parent))
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        parser.exit(1, 'Release admission refused; materials, revision and immutable local images must be verified.\n')
    print(json.dumps({'review_only': True, 'formal_operations_executed': False,
        'revision': REVISION, 'commit': data['commit'], 'images': data['images'],
        'rollback_commit': data['rollback_commit'], 'rollback_images': data['rollback_images'],
        'config_template_version': data['config_template_version'],
        'switches_closed': True, 'compose': 'compose.release.yaml'}, sort_keys=True))

if __name__ == '__main__': main()
