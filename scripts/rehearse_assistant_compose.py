"""Isolated validation of the release Compose using synthetic env files only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from release_assistant import validate_test_project

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--docker', default='F:/my-campus-dev/docker/app/resources/bin/docker.exe')
parser.add_argument('--image-project', type=validate_test_project, default='my-campus-ai-m6-verify')
parser.add_argument('--project', type=validate_test_project, default='my-campus-ai-m6-release-smoke')
args = parser.parse_args()
output = args.output.resolve()
if output.drive.upper() != 'F:' or output.exists(): parser.error('New F-drive output directory required')
output.mkdir(parents=True)
project, docker = args.project, args.docker
if not project.startswith('my-campus-ai-m6-release'): parser.error('Dedicated release test project required')
for folder in ('knowledge', 'faiss'):
    (output/'data'/folder).mkdir(parents=True)
campus = ('CAMPUS_DATABASE_URL=mysql+asyncmy://my_campus:synthetic-only@mysql:3306/my_campus_test?charset=utf8mb4\n'
          'CAMPUS_REDIS_URL=redis://redis:6379/0\n')
files = {'campus':campus+'CAMPUS_JWT_SECRET=m6-synthetic-compose-smoke-only-signing-key\n',
    'mcp-database':campus, 'knowledge':'', 'empty':'',
    'mcp':'CAMPUS_MCP_SIGNING_SECRET=m6-synthetic-compose-smoke-independent-secret\n',
    'mysql':'MYSQL_DATABASE=my_campus_test\nMYSQL_USER=my_campus\nMYSQL_PASSWORD=synthetic-only\nMYSQL_ROOT_PASSWORD=synthetic-root-only\n'}
for name, value in files.items():
    (output/(name+'.env')).write_text(value, encoding='utf-8')
env = dict(os.environ, CAMPUS_DATA_ROOT=(output/'data').as_posix(),
    COMPOSE_ENV_FILES=(output/'empty.env').as_posix(),
    RELEASE_BACKEND_IMAGE='my-campus-backend:'+args.image_project,
    RELEASE_ASSISTANT_IMAGE='my-campus-assistant:'+args.image_project,
    RELEASE_MCP_IMAGE='my-campus-assistant:'+args.image_project,
    RELEASE_FRONTEND_IMAGE='my-campus-frontend:'+args.image_project,
    RELEASE_MYSQL_IMAGE='mysql:8.4', RELEASE_REDIS_IMAGE='redis:7.4-alpine')
for variable, name in [('CAMPUS','campus'),('MYSQL','mysql'),('KNOWLEDGE','knowledge'),
                       ('MCP_DATABASE','mcp-database'),('MCP','mcp')]:
    env['RELEASE_'+variable+'_ENV_FILE'] = (output/(name+'.env')).as_posix()
override = output/'isolated.yaml'
override.write_text('''services:
  mysql:
    volumes: !override [{type: tmpfs, target: /var/lib/mysql}]
  redis:
    volumes: !override [{type: tmpfs, target: /data}]
  api:
    ports: !reset []
  frontend:
    ports: !reset []
''')
base = [docker,'compose','--env-file',str(output/'empty.env'),'-p',project,
    '-f',str(root/'compose.release.yaml'),'-f',str(override),'--profile','private-mcp']
report = {'passed':False, 'project':project, 'synthetic_only':True, 'stages':[],
    'compose_sha256':hashlib.sha256((root/'compose.release.yaml').read_bytes()).hexdigest()}
def run(name, command):
    result = subprocess.run(command, env=env, cwd=root, capture_output=True, timeout=180)
    (output/(name+'.log')).write_bytes(result.stdout+result.stderr)
    report['stages'].append({'name':name,'exit':result.returncode})
    if result.returncode: raise RuntimeError('Isolated Compose stage failed: '+name)
    return result.stdout
snapshot = '''import asyncio, hashlib, json
from sqlalchemy import text
from sqlalchemy.engine import make_url
from app.config import load_settings
from app.database import Database
async def main():
 s=load_settings()
 if make_url(s.database_url).database!='my_campus_test': raise ValueError('Test database required')
 d=Database(s.database_url)
 try:
  async with d.engine.connect() as c:
   names=(await c.execute(text('SHOW TABLES'))).scalars().all()
   result={}
   for n in sorted(names):
    rows=(await c.execute(text('SELECT * FROM `'+n+'`'))).mappings().all()
    result[n]=sorted(json.dumps(dict(r),sort_keys=True,default=str) for r in rows)
   print(hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest())
 finally: await d.dispose()
asyncio.run(main())'''
owned = False
try:
    if run('empty',base+['ps','-a','-q']).strip(): raise ValueError('Refuse existing release test project')
    owned = True
    run('infra',base+['up','-d','--wait','mysql','redis'])
    run('migration',base+['run','--rm','migrate'])
    services = ['api','worker','assistant-worker','campus-mcp','frontend']
    run('start',base+['up','-d','--wait']+services)
    before = run('before',base+['exec','-T','api','python','-B','-c',snapshot]).strip()
    run('repeat-start',base+['up','-d','--wait']+services)
    after = run('after',base+['exec','-T','api','python','-B','-c',snapshot]).strip()
    if before != after: raise RuntimeError('Repeated startup changed persistent data')
    report['repeated_start_preserved_all_tables'] = True
    checker = [sys.executable,'-B',str(root/'scripts/check_assistant_operations.py'),
        '--docker',docker,'--project',project,'--compose-file',str(root/'compose.release.yaml'),
        '--compose-file',str(override)]
    for service in ['mysql','redis']+services:
        checker += ['--service',service]
    report['operations'] = json.loads(run('operations',checker))
    report['images'] = json.loads(run('images',base+['images','--format','json']))
    report['passed'] = True
finally:
    if owned:
        try: run('cleanup',base+['down'])
        except Exception:
            report['passed']=False
            report['cleanup_failed']=True
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'passed':report['passed'],'report':str(output/'report.json')}))
raise SystemExit(0 if report['passed'] else 1)
