import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

spec = importlib.util.spec_from_file_location('release', Path(__file__).parents[1]/'release_assistant.py')
release = importlib.util.module_from_spec(spec)
if spec.loader: spec.loader.exec_module(release)

class GateTests(unittest.TestCase):
    def test_valid_report_and_actual_images_are_bound(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            image = 'image@sha256:'+'b'*64
            report = {'passed':True, 'commit':'a'*40, 'cloud_calls':0,
                'tests':{'backend':{'passed':708,'failed':0,'skipped':0}},
                'stages':[{'name':name,'exit':0} for name in release.REQUIRED_STAGES],
                'images':{k:'sha256:'+'b'*64 for k in ('backend','assistant','frontend','rollback')}}
            evidence = base/'report.json'
            evidence.write_text(json.dumps(report))
            item = {'path':'report.json','sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
            data = {'revision':release.REVISION, 'commit':'a'*40, 'rollback_commit':'a'*40,
                'config_template_version':'m6-closed-v1', 'rollback_images':{k:image for k in release.SERVICES},
                'valid_until':'2099-01-01T00:00:00Z', 'assistant_enabled':False, 'allow_campus_data':False,
                'images':{k:image for k in release.SERVICES}, 'admission':{k:item for k in release.MATERIALS}}
            release.validate_manifest(data, base)
            for field, value in [('valid_until','2000-01-01T00:00:00Z'),
                                 ('revision','0006_assistant'), ('assistant_enabled',True)]:
                with self.subTest(field=field), self.assertRaises(ValueError):
                    release.validate_manifest(dict(data, **{field:value}), base)
            for material in ('accounts','notice'):
                with self.subTest(material=material), self.assertRaises(ValueError):
                    release.validate_manifest(dict(data, admission=dict(data['admission'], **{material:None})), base)
            inspected = {'Id':'sha256:'+'b'*64, 'RepoDigests':[image],
                'Config':{'Labels':{'org.opencontainers.image.revision':'a'*40}}}
            with patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,json.dumps([inspected]))):
                release.verify_images(data, 'docker', report)
                report['images']['backend'] = 'sha256:'+'c'*64
                with self.assertRaisesRegex(ValueError, 'differs from verification'):
                    release.verify_images(data, 'docker', report)
                report['images']['backend'] = inspected['Id']
                report['images']['rollback'] = 'sha256:'+'c'*64
                with self.assertRaisesRegex(ValueError, 'Rollback image differs'):
                    release.verify_images(data, 'docker', report)
            inspected['RepoDigests'] = []
            with patch.object(release.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,json.dumps([inspected]))):
                with self.assertRaisesRegex(ValueError, 'digest differs'):
                    release.verify_images(data, 'docker', report)

    def test_verification_must_pass_and_match_source_without_skips(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            evidence = base/'report.json'
            data = {'revision':release.REVISION, 'commit':'a'*40,
                'valid_until':'2099-01-01T00:00:00Z', 'assistant_enabled':False,
                'allow_campus_data':False, 'images':{k:'image@sha256:'+'b'*64 for k in release.SERVICES}}
            for report in ({'passed':False, 'commit':'a'*40},
                           {'passed':True, 'commit':'c'*40},
                           {'passed':True, 'commit':'a'*40, 'tests':{'backend':{'passed':708,'failed':0,'skipped':1}}}):
                evidence.write_text(json.dumps(report))
                item = {'path':'report.json','sha256':hashlib.sha256(evidence.read_bytes()).hexdigest()}
                data['admission'] = {k:item for k in release.MATERIALS}
                with self.assertRaisesRegex(ValueError, 'verification'):
                    release.validate_manifest(data, base)

    def test_missing_admission_refuses_before_docker(self):
        with self.assertRaisesRegex(ValueError, 'admission'):
            release.validate_manifest({'revision':'0007_assistant_access'}, Path('.'))

    def test_floating_image_refuses(self):
        with self.assertRaisesRegex(ValueError, 'digest'):
            release.validate_image('backend:latest')

    def test_project_refuses_production_or_existing_generic_name(self):
        for name in ['my-campus', 'my-campus-ai-m5-release', 'my-campus-ai-m6-test', 'x;bad']:
            with self.assertRaises(ValueError): release.validate_test_project(name)
        self.assertEqual(release.validate_test_project('my-campus-ai-m6-release'), 'my-campus-ai-m6-release')

    def test_approved_material_hash_is_checked(self):
        temporary = Path(__file__).parents[2]/'.workbuddy'
        temporary.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary) as folder:
            path = Path(folder)/'approved.txt'
            path.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'hash'):
                release.validate_evidence({'path':str(path), 'sha256':'0'*64}, Path(folder))

if __name__ == '__main__': unittest.main()
