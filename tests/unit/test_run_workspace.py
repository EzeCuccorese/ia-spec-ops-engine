"""Unit tests for scripts/run-workspace.py.

Style mirrors bin/generate-workspace/tests/test_create_workspace.py:
- unittest.TestCase
- tempfile + Path fixtures
- unittest.mock.patch for I/O boundaries

The script is loaded via importlib because the filename uses a hyphen.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from devscripts.cli import run_local as run_workspace


class TestAssignPort(unittest.TestCase):
    def test_port_is_deterministic(self):
        a = run_workspace.assign_port('ms-orders-management')
        b = run_workspace.assign_port('ms-orders-management')
        self.assertEqual(a, b)

    def test_port_is_within_range(self):
        for name in ['ms-orders', 'gres-grecosystem-bff', 'valiant-rural-productor']:
            port = run_workspace.assign_port(name)
            self.assertGreaterEqual(port, 8200)
            self.assertLessEqual(port, 8899)

    def test_different_names_likely_get_different_ports(self):
        names = ['ms-orders', 'ms-loans', 'ms-valiant-cgf-ars', 'gres-bff', 'productor']
        ports = {run_workspace.assign_port(n) for n in names}
        self.assertGreaterEqual(len(ports), len(names) - 1)


class TestIsNoise(unittest.TestCase):
    def test_exact_match_noise(self):
        for key in ['HOSTNAME', 'HOME', 'PATH', 'USER', 'SHELL', 'PWD']:
            self.assertTrue(run_workspace._is_noise(key), key)

    def test_prefix_noise(self):
        self.assertTrue(run_workspace._is_noise('KUBERNETES_PORT_443_TCP'))
        self.assertTrue(run_workspace._is_noise('JAVA_HOME'))
        self.assertTrue(run_workspace._is_noise('LC_ALL'))

    def test_suffix_noise(self):
        self.assertTrue(run_workspace._is_noise('MS_ORDERS_SERVICE_HOST'))
        self.assertTrue(run_workspace._is_noise('MY_SERVICE_PORT'))

    def test_keeps_application_vars(self):
        self.assertFalse(run_workspace._is_noise('SPRING_PROFILES_ACTIVE'))
        self.assertFalse(run_workspace._is_noise('MS_ORDERS_URL'))
        self.assertFalse(run_workspace._is_noise('AUTH0_CLIENT_ID'))


class TestServiceNameFromSubdomain(unittest.TestCase):
    def test_strips_namespace_prefix(self):
        self.assertEqual(
            run_workspace._service_name_from_subdomain('core-ms-orders-faf-abc', strip_env=False),
            'ms-orders-faf-abc',
        )

    def test_strips_merchants_prefix(self):
        self.assertEqual(
            run_workspace._service_name_from_subdomain('merchants-ms-merchant-management-staging-xyz', strip_env=False),
            'ms-merchant-management-staging-xyz',
        )

    def test_strips_prt_bgal_prefix(self):
        self.assertEqual(
            run_workspace._service_name_from_subdomain('prt-bgal-ms-valiant-csf-ars-faf-abc', strip_env=False),
            'ms-valiant-csf-ars-faf-abc',
        )

    def test_passthrough_unknown_prefix(self):
        self.assertEqual(
            run_workspace._service_name_from_subdomain('unknown-prefix-foo'),
            'unknown-prefix-foo',
        )


class TestWireUrls(unittest.TestCase):
    def test_replaces_in_workspace_repo_url_with_localhost(self):
        env_vars = {
            'MS_ORDERS_URL': 'https://core-ms-orders-faf-abc.dev.ai-dev.com',
        }
        running = {'ms-orders': 8300}
        result, _ = run_workspace.wire_urls(env_vars, running)
        self.assertEqual(result['MS_ORDERS_URL'], 'http://localhost:8300')

    def test_preserves_path_when_replacing(self):
        env_vars = {
            'BFF': 'https://frontend-gres-grecosystem-bff-staging-xxx.dev.ai-dev.com/v1/gres',
        }
        running = {'gres-grecosystem-bff': 8763}
        result, _ = run_workspace.wire_urls(env_vars, running)
        self.assertEqual(result['BFF'], 'http://localhost:8763/v1/gres')

    def test_leaves_unmatched_urls_untouched(self):
        env_vars = {
            'EXTERNAL': 'https://core-ms-foo-faf-xyz.dev.ai-dev.com/api',
        }
        running = {'ms-orders': 8300}  # ms-foo NOT running locally
        result, _ = run_workspace.wire_urls(env_vars, running)
        self.assertEqual(result['EXTERNAL'], env_vars['EXTERNAL'])

    def test_ignores_non_ai_urls(self):
        env_vars = {'OTHER': 'https://api.example.com/foo'}
        result, _ = run_workspace.wire_urls(env_vars, {'ms-orders': 8300})
        self.assertEqual(result['OTHER'], env_vars['OTHER'])


class TestWireDbUrls(unittest.TestCase):
    def test_promotes_mongo_srv_uri_to_canonical(self):
        pod = {'MONGO_ORDERS_URI': 'mongodb+srv://u:p@host.mongodb.net/staging-orders?w=majority',
               'OTHER': 'foo'}
        result = run_workspace.wire_db_urls(pod)
        self.assertEqual(result, {
            'SPRING_DATA_MONGODB_URI':
                'mongodb+srv://u:p@host.mongodb.net/staging-orders?w=majority'
        })

    def test_promotes_plain_mongo_uri(self):
        pod = {'DB': 'mongodb://localhost:27017/orders'}
        result = run_workspace.wire_db_urls(pod)
        self.assertEqual(result['SPRING_DATA_MONGODB_URI'], 'mongodb://localhost:27017/orders')

    def test_detection_is_by_value_not_var_name(self):
        # Variable named arbitrarily — still detected by its mongodb:// value.
        pod = {'WHATEVER_NAME': 'mongodb+srv://h/db'}
        result = run_workspace.wire_db_urls(pod)
        self.assertEqual(result['SPRING_DATA_MONGODB_URI'], 'mongodb+srv://h/db')

    def test_noop_when_canonical_mongo_already_set(self):
        pod = {'SPRING_DATA_MONGODB_URI': 'mongodb://canonical',
               'MONGO_ORDERS_URI': 'mongodb://other'}
        result = run_workspace.wire_db_urls(pod)
        self.assertNotIn('SPRING_DATA_MONGODB_URI', result)

    def test_skips_ambiguous_multiple_mongo_uris(self):
        pod = {'A': 'mongodb://one', 'B': 'mongodb://two'}
        result = run_workspace.wire_db_urls(pod)
        self.assertNotIn('SPRING_DATA_MONGODB_URI', result)

    def test_dedupes_identical_mongo_uri_under_two_names(self):
        pod = {'A': 'mongodb://same', 'B': 'mongodb://same'}
        result = run_workspace.wire_db_urls(pod)
        self.assertEqual(result['SPRING_DATA_MONGODB_URI'], 'mongodb://same')

    def test_promotes_postgres_url_and_prepends_jdbc(self):
        pod = {'DB': 'postgresql://u:p@host:5432/db'}
        result = run_workspace.wire_db_urls(pod)
        self.assertEqual(result['SPRING_DATASOURCE_URL'], 'jdbc:postgresql://u:p@host:5432/db')

    def test_normalizes_postgres_short_scheme_to_postgresql(self):
        # postgres:// must become jdbc:postgresql:// — jdbc:postgres:// has no driver.
        pod = {'DB': 'postgres://u:p@host:5432/db'}
        result = run_workspace.wire_db_urls(pod)
        self.assertEqual(result['SPRING_DATASOURCE_URL'], 'jdbc:postgresql://u:p@host:5432/db')

    def test_keeps_existing_jdbc_prefix(self):
        pod = {'DB': 'jdbc:postgresql://host:5432/db'}
        result = run_workspace.wire_db_urls(pod)
        self.assertEqual(result['SPRING_DATASOURCE_URL'], 'jdbc:postgresql://host:5432/db')

    def test_skips_composed_postgres_rds_vars(self):
        # No single URI value present — composed from discrete RDS_* vars.
        pod = {'RDS_HOST': 'host', 'RDS_PORT': '5432', 'RDS_NAME': 'agreement'}
        result = run_workspace.wire_db_urls(pod)
        self.assertEqual(result, {})

    def test_no_db_returns_empty(self):
        result = run_workspace.wire_db_urls({'FOO': 'bar', 'URL': 'https://x.com'})
        self.assertEqual(result, {})


class TestParseDotenv(unittest.TestCase):
    def test_parses_simple_lines(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write('A=1\nB="quoted"\nC=\'single\'\n')
            f.write('# comment\n\n')
            f.write('D = spaced\n')
            path = Path(f.name)
        try:
            result = run_workspace._parse_dotenv(path)
            self.assertEqual(result['A'], '1')
            self.assertEqual(result['B'], 'quoted')
            self.assertEqual(result['C'], 'single')
            self.assertEqual(result['D'], 'spaced')
            self.assertNotIn('# comment', result)
        finally:
            path.unlink()


class TestIsFeFramework(unittest.TestCase):
    def _mkrepo(self, pkg: dict) -> Path:
        tmp = Path(tempfile.mkdtemp())
        (tmp / 'package.json').write_text(json.dumps(pkg))
        self.addCleanup(self._rmtree, tmp)
        return tmp

    @staticmethod
    def _rmtree(p: Path):
        import shutil as _sh
        _sh.rmtree(str(p), ignore_errors=True)

    def test_detects_next_by_dependency(self):
        repo = self._mkrepo({'dependencies': {'next': '14.0.0', 'react': '18'}})
        self.assertEqual(run_workspace._is_fe_framework(repo), 'next')

    def test_detects_next_by_script(self):
        repo = self._mkrepo({'scripts': {'dev': 'next', 'build': 'next build'}})
        self.assertEqual(run_workspace._is_fe_framework(repo), 'next')

    def test_detects_vite_by_dependency(self):
        repo = self._mkrepo({'devDependencies': {'vite': '5.4.10'}})
        self.assertEqual(run_workspace._is_fe_framework(repo), 'vite')

    def test_detects_vite_by_script(self):
        repo = self._mkrepo({'scripts': {'dev': 'vite --host'}})
        self.assertEqual(run_workspace._is_fe_framework(repo), 'vite')

    def test_returns_none_for_plain_node(self):
        repo = self._mkrepo({
            'dependencies': {'express': '4.18'},
            'scripts': {'start': 'node server.js'},
        })
        self.assertIsNone(run_workspace._is_fe_framework(repo))

    def test_returns_none_when_no_package_json(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rmtree, tmp)
        self.assertIsNone(run_workspace._is_fe_framework(tmp))


class TestDetectService(unittest.TestCase):
    @staticmethod
    def _rmtree(p: Path):
        import shutil as _sh
        _sh.rmtree(str(p), ignore_errors=True)

    def test_detects_spring_gradle(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rmtree, tmp)
        (tmp / 'gradlew').write_text('#!/bin/sh\n')
        (tmp / 'build.gradle').write_text('')
        java_dir = tmp / 'src' / 'main' / 'java' / 'com'
        java_dir.mkdir(parents=True)
        (java_dir / 'FooApplication.java').write_text(
            '@SpringBootApplication\npublic class FooApplication {}'
        )
        svc = run_workspace.detect_service(tmp)
        self.assertIsNotNone(svc)
        self.assertEqual(svc['type'], 'spring-gradle')
        self.assertIn('bootRun', svc['cmd'])

    def test_detects_next_with_port_placeholder(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rmtree, tmp)
        (tmp / 'package.json').write_text(json.dumps({
            'dependencies': {'next': '14'},
            'scripts': {'dev': 'next', 'build': 'next build'},
        }))
        svc = run_workspace.detect_service(tmp)
        self.assertEqual(svc['type'], 'next')
        self.assertIn('__PORT__', svc['cmd'])
        self.assertIn('--port', svc['cmd'])

    def test_detects_vite_with_port_placeholder(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rmtree, tmp)
        (tmp / 'package.json').write_text(json.dumps({
            'devDependencies': {'vite': '5'},
            'scripts': {'dev': 'vite --host'},
        }))
        svc = run_workspace.detect_service(tmp)
        self.assertEqual(svc['type'], 'vite')
        self.assertIn('__PORT__', svc['cmd'])

    def test_returns_none_for_unrunnable_dir(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rmtree, tmp)
        self.assertIsNone(run_workspace.detect_service(tmp))


class TestSpringContextPath(unittest.TestCase):
    @staticmethod
    def _rmtree(p: Path):
        import shutil as _sh
        _sh.rmtree(str(p), ignore_errors=True)

    def _mkrepo_with_app_yaml(self, content: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rmtree, tmp)
        d = tmp / 'src' / 'main' / 'resources'
        d.mkdir(parents=True)
        (d / 'application.yaml').write_text(content)
        return tmp

    def test_reads_context_path_from_yaml(self):
        repo = self._mkrepo_with_app_yaml(
            'server:\n  servlet:\n    context-path: /ms-orders\n'
        )
        self.assertEqual(run_workspace._spring_context_path(repo), '/ms-orders')

    def test_returns_empty_when_no_context_path(self):
        repo = self._mkrepo_with_app_yaml('server:\n  port: 8080\n')
        self.assertEqual(run_workspace._spring_context_path(repo), '')


class TestNodeHealthPath(unittest.TestCase):
    @staticmethod
    def _rmtree(p: Path):
        import shutil as _sh
        _sh.rmtree(str(p), ignore_errors=True)

    def test_finds_version_prefix_and_health(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rmtree, tmp)
        (tmp / 'app').mkdir()
        (tmp / 'app' / 'config.js').write_text(
            "const versionPath = '/v1/gres';\n"
        )
        (tmp / 'app' / 'routes.js').write_text(
            "app.use('/health', require('./health'));\n"
        )
        result = run_workspace._node_health_path(tmp)
        self.assertEqual(result, '/v1/gres/health')

    def test_returns_none_when_nothing_found(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(self._rmtree, tmp)
        self.assertIsNone(run_workspace._node_health_path(tmp))


class TestServiceLink(unittest.TestCase):
    def test_next_returns_app_link(self):
        label, url = run_workspace.service_link('next', 8224, Path('/tmp'))
        self.assertEqual(label, 'App')
        self.assertEqual(url, 'http://localhost:8224/')

    def test_vite_returns_app_link(self):
        label, url = run_workspace.service_link('vite', 8298, Path('/tmp'))
        self.assertEqual(label, 'App')
        self.assertEqual(url, 'http://localhost:8298/')

    def test_spring_returns_swagger_link(self):
        with patch.object(run_workspace, '_spring_context_path', return_value=''):
            label, url = run_workspace.service_link('spring-gradle', 8308, Path('/tmp'))
        self.assertEqual(label, 'Swagger')
        self.assertIn('/swagger-ui/index.html', url)
        self.assertIn(':8308', url)

    def test_spring_with_context_path(self):
        with patch.object(run_workspace, '_spring_context_path', return_value='/ms-orders'):
            label, url = run_workspace.service_link('spring-maven', 8400, Path('/tmp'))
        self.assertEqual(url, 'http://localhost:8400/ms-orders/swagger-ui/index.html')

    def test_node_with_health_path(self):
        with patch.object(run_workspace, '_node_health_path', return_value='/v1/gres/health'):
            label, url = run_workspace.service_link('node', 8763, Path('/tmp'))
        self.assertEqual(label, 'Health')
        self.assertEqual(url, 'http://localhost:8763/v1/gres/health')

    def test_node_without_health_path_falls_back_to_app(self):
        with patch.object(run_workspace, '_node_health_path', return_value=None):
            label, url = run_workspace.service_link('node', 8500, Path('/tmp'))
        self.assertEqual(label, 'App')
        self.assertEqual(url, 'http://localhost:8500/')


class TestFindPod(unittest.TestCase):
    def test_finds_running_pod_by_service_and_env(self):
        stdout = (
            'NAME                                          READY  STATUS    AGE\n'
            'core-ms-orders-faf-1234-abc                    2/2    Running   1h\n'
            'merchants-ms-orders-staging-9999-xyz           2/2    Running   3h\n'
        )
        mock_proc = MagicMock(returncode=0, stdout=stdout, stderr='')
        with patch.object(run_workspace, '_kubectl', return_value=mock_proc):
            pod, err = run_workspace.find_pod('ms-orders', 'staging', 'ctx', 'staging')
        self.assertEqual(pod, 'merchants-ms-orders-staging-9999-xyz')
        self.assertIsNone(err)

    def test_returns_none_when_kubectl_fails(self):
        mock_proc = MagicMock(returncode=1, stdout='', stderr='no auth')
        with patch.object(run_workspace, '_kubectl', return_value=mock_proc):
            pod, err = run_workspace.find_pod('ms-orders', 'faf', 'ctx', 'sandbox')
        self.assertIsNone(pod)
        self.assertEqual(err, 'no auth')

    def test_returns_none_when_no_match(self):
        mock_proc = MagicMock(returncode=0, stdout='NAME\nfoo\n', stderr='')
        with patch.object(run_workspace, '_kubectl', return_value=mock_proc):
            pod, err = run_workspace.find_pod('ms-orders', 'faf', 'ctx', 'sandbox')
        self.assertIsNone(pod)
        self.assertIsNone(err)

    def test_reports_when_pod_not_running(self):
        stdout = (
            'NAME                          READY  STATUS    AGE\n'
            'core-ms-orders-faf-abc        0/2    Pending   30s\n'
        )
        mock_proc = MagicMock(returncode=0, stdout=stdout, stderr='')
        with patch.object(run_workspace, '_kubectl', return_value=mock_proc):
            pod, err = run_workspace.find_pod('ms-orders', 'faf', 'ctx', 'sandbox')
        self.assertIsNone(pod)
        self.assertIn('Pending', err)


class TestResolveContext(unittest.TestCase):
    def test_picks_non_prod_for_dev(self):
        with patch.object(run_workspace, '_get_kubectl_contexts',
                          return_value=['arn:...:cluster/example-dev', 'arn:...:cluster/example-prod']):
            ctx = run_workspace._resolve_context('dev')
        self.assertIn('dev', ctx)

    def test_picks_prod_for_prod(self):
        with patch.object(run_workspace, '_get_kubectl_contexts',
                          return_value=['arn:...:cluster/example-dev', 'arn:...:cluster/example-prod']):
            ctx = run_workspace._resolve_context('prod')
        self.assertIn('prod', ctx)

    def test_returns_none_when_no_match(self):
        with patch.object(run_workspace, '_get_kubectl_contexts', return_value=[]):
            self.assertIsNone(run_workspace._resolve_context('dev'))


if __name__ == '__main__':
    unittest.main()
